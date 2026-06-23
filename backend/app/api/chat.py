# Chat 会话/消息 API 路由

import uuid
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.config import settings

logger = logging.getLogger(__name__)
from app.schemas.chat import (
    ChatMessageRequest,
    ChatMessageResponse,
    SessionCreateResponse,
    ConversationMessagesResponse,
    ConversationDetail,
    MessageDetail,
)
from app.schemas.common import BaseResponse
from app.services.session_service import session_service
from app.services.llm_service import get_llm
from app.services.knowledge_service import knowledge_service
from app.services.brand_service import BrandIdentificationService

brand_service = BrandIdentificationService()
from app.graph.workflow import agent_workflow
from app.graph.state import WorkflowState
from app.nodes.preprocess import check_transfer_keyword, check_greeting
from app.nodes.intent_recognition import INTENT_LABELS
from app.nodes.human_transfer import HIGH_RISK_KEYWORDS, UNSUPPORTED_OPERATIONS

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post("/sessions", response_model=BaseResponse)
async def create_session(
    user_id: Optional[str] = None,
    business_area: str = "dashcam",
    entry_point: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """创建新会话 → 返回 session_id + 欢迎语 + FAQ卡片"""
    conv = await session_service.create_session(
        db=db,
        user_id=user_id,
        business_area=business_area,
        entry_point=entry_point,
    )
    await db.commit()

    # 获取FAQ卡片
    faq_cards = await knowledge_service.get_faq_cards(db, business_area)
    cards = [
        {"id": c.id, "card_code": c.card_code, "title": c.title, "category": c.category}
        for c in faq_cards
    ]

    return BaseResponse(
        data=SessionCreateResponse(
            session_id=conv.session_id,
            welcome_message="您好! 我是AI客服助手, 请问有什么可以帮您的?",
            faq_cards=cards,
        ).model_dump()
    )


@router.get("/sessions/{session_id}", response_model=BaseResponse)
async def get_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取会话详情 (含消息历史)"""
    conv = await session_service.get_session_with_messages(db, session_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    messages = []
    for msg in conv.messages:
        messages.append(MessageDetail(
            message_id=msg.message_id,
            seq=msg.seq,
            role=msg.role,
            content=msg.content,
            content_type=msg.content_type or "text",
            action=msg.action,
            reply_type=msg.reply_type,
            knowledge_code=msg.knowledge_code,
            created_at=msg.created_at.isoformat() if msg.created_at else None,
        ))

    return BaseResponse(
        data=ConversationMessagesResponse(
            conversation=ConversationDetail(
                session_id=conv.session_id,
                user_id=conv.user_id,
                business_area=conv.business_area,
                status=conv.status,
                message_count=conv.message_count,
                ai_resolved=conv.ai_resolved or False,
                transfer_count=conv.transfer_count or 0,
                started_at=conv.started_at.isoformat() if conv.started_at else None,
                ended_at=conv.ended_at.isoformat() if conv.ended_at else None,
            ),
            messages=messages,
        ).model_dump()
    )


@router.post("/message", response_model=BaseResponse)
async def send_message(
    req: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """核心接口: 发送消息, 触发 LangGraph 工作流, 返回 AI 回复"""
    session_id = req.session_id

    # ============================================
    # Step 1: 获取或创建会话
    # ============================================
    if session_id:
        conv = await session_service.get_session(db, session_id)
        if not conv:
            conv = await session_service.create_session(
                db=db,
                user_id=req.user_id,
                business_area=req.business_area,
                entry_point=req.entry_point,
            )
            session_id = conv.session_id
    else:
        conv = await session_service.create_session(
            db=db,
            user_id=req.user_id,
            business_area=req.business_area,
            entry_point=req.entry_point,
        )
        session_id = conv.session_id

    # 保存用户消息
    user_msg = await session_service.add_message(
        db=db,
        conversation_id=conv.id,
        role="user",
        content=req.content,
        content_type=req.content_type,
        media_url=req.media_url,
    )
    await db.commit()

    # ============================================
    # Step 2: 构建初始 WorkflowState
    # ============================================
    initial_state: WorkflowState = {
        "query": req.content,
        "session_id": session_id,
        "user_id": req.user_id or "",
        "business_area": req.business_area,
        "channel": "miniprogram",
        "entry_point": req.entry_point or "",
        "message_type": req.content_type,
        "media_url": req.media_url,
        "messages": [],
        "dialogue_round": conv.message_count or 0,
        "consecutive_fail_count": conv.consecutive_fail or 0,
        "collected_slots": {},
        "should_transfer": False,
        "response_type": "fallback",
        "response_attachments": [],
        "follow_up_questions": [],
    }

    # ============================================
    # Step 2.5: 多轮上下文 — 检查是否有待处理的品牌追问
    # ============================================
    # 上一轮若追问了品牌, 当前消息若能识别出品牌, 直接返回该品牌对应知识
    pending = await session_service.get_pending_context(db, session_id)
    if pending and pending.get("type") == "brand_collection":
        brand_result = await brand_service.identify_by_keyword(req.content)
        if brand_result and brand_result.confidence >= 0.8:
            # 识别到品牌 → 取该品牌、该主题的知识
            brand_knowledge = await _get_brand_knowledge(
                db, req.business_area,
                pending.get("category_l2", ""),
                brand_result.brand_name,
            )
            if brand_knowledge:
                await session_service.clear_pending_context(db, session_id)
                attachments = []
                if brand_knowledge.need_attachment:
                    for att in brand_knowledge.attachments:
                        attachments.append({"type": att.file_type or "link", "url": att.file_url, "name": att.file_name})
                reply_content = await _polish_answer(req.content, brand_knowledge)
                ai_msg = await session_service.add_message(
                    db=db,
                    conversation_id=conv.id,
                    role="assistant",
                    content=reply_content,
                    action="auto_reply",
                    reply_type="knowledge_answer",
                    knowledge_id=brand_knowledge.id,
                    knowledge_code=brand_knowledge.knowledge_code,
                    intent_result={"intent": "knowledge_query", "brand": brand_result.brand_name, "via": "brand_collection"},
                )
                await session_service.update_consecutive_fail(db, session_id, increment=False)
                await db.commit()
                return BaseResponse(
                    data=ChatMessageResponse(
                        session_id=session_id,
                        message_id=ai_msg.message_id,
                        seq=ai_msg.seq,
                        content=reply_content,
                        response_type="knowledge_answer",
                        knowledge_code=brand_knowledge.knowledge_code,
                        attachments=attachments,
                        follow_up_questions=_gen_follow_ups(brand_knowledge),
                        evaluation_prompt="这个回答有帮助吗?",
                    ).model_dump()
                )
        # 未识别出品牌 → 清除pending, 走正常流程 (用户可能改问别的)
        await session_service.clear_pending_context(db, session_id)

    # VIN 收集 pending: 上一轮追问了VIN, 当前消息若含VIN, 直接调接口查询
    if pending and pending.get("type") == "vin_collection":
        vin = _extract_vin(req.content)
        if vin:
            await session_service.clear_pending_context(db, session_id)
            from app.integrations.platform_client import platform_client
            qtype = pending.get("query_type_code", "QRY002")
            device = await platform_client.query_device_by_vin(vin)
            if device:
                lines = ["已为您查询到以下设备信息:"]
                field_labels = {
                    "plate_number": "车牌号",
                    "terminal_id": "记录仪设备号",
                    "service_expiry": "到期时间",
                    "vin": "车架号(VIN)",
                }
                for f, label in field_labels.items():
                    val = device.get(f)
                    if val:
                        lines.append(f"• {label}: {val}")
                content = "\n".join(lines)
                reply_type = "query_result"
            else:
                content = "未查询到该 VIN 对应的设备信息。请确认车架号(VIN)是否正确, 或联系人工客服。"
                reply_type = "query_empty"

            ai_msg = await session_service.add_message(
                db=db,
                conversation_id=conv.id,
                role="assistant",
                content=content,
                action="query",
                reply_type=reply_type,
                query_type_code=qtype,
                intent_result={"intent": "live_query", "vin": vin, "via": "vin_collection"},
            )
            await session_service.update_consecutive_fail(db, session_id, increment=False)
            await db.commit()
            return BaseResponse(
                data=ChatMessageResponse(
                    session_id=session_id,
                    message_id=ai_msg.message_id,
                    seq=ai_msg.seq,
                    content=content,
                    response_type="query_result",
                    evaluation_prompt="这个回答有帮助吗?",
                ).model_dump()
            )
        # 未提取到VIN → 清除pending, 走正常流程
        await session_service.clear_pending_context(db, session_id)

    # ============================================
    # Step 3: 快速通道 — 转人工/高风险/超出范围/问候语
    # ============================================
    # 高风险词 (投诉/退款/12315...) 或超出AI范围操作 (修改绑定/激活...) → 直接转人工
    needs_transfer = (
        check_transfer_keyword(req.content)
        or any(kw in req.content for kw in HIGH_RISK_KEYWORDS)
        or any(op in req.content for op in UNSUPPORTED_OPERATIONS)
    )

    if needs_transfer:
        # 判断转人工原因
        if check_transfer_keyword(req.content):
            reason_type, reason = "user_request", "用户要求转人工"
        elif any(kw in req.content for kw in HIGH_RISK_KEYWORDS):
            hit = next(kw for kw in HIGH_RISK_KEYWORDS if kw in req.content)
            reason_type, reason = "risk", f"检测到高风险关键词: {hit}"
        else:
            hit = next(op for op in UNSUPPORTED_OPERATIONS if op in req.content)
            reason_type, reason = "out_of_scope", f"超出AI服务范围: {hit}"

        await session_service.update_session_status(
            db, session_id, "transferred",
            transfer_count=(conv.transfer_count or 0) + 1,
        )
        await db.commit()

        transfer_msg = f"检测到您的问题需要人工处理（{reason}），正在为您转接人工客服，请稍候..."
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content=transfer_msg,
            action="transfer",
            reply_type="handoff",
        )
        await db.commit()

        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=ai_msg.content,
                response_type="transfer",
                should_transfer=True,
                evaluation_prompt="感谢您的耐心等待, 人工客服将尽快为您服务。",
            ).model_dump()
        )

    if check_greeting(req.content):
        faq_cards = await knowledge_service.get_faq_cards(db, req.business_area)
        follow_ups = [c.title for c in faq_cards[:5]]

        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content="您好! 我是AI客服助手, 请问有什么可以帮您的?",
            action="auto_reply",
            reply_type="greeting",
        )
        await session_service.update_consecutive_fail(db, session_id, increment=False)
        await db.commit()

        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=ai_msg.content,
                response_type="greeting",
                follow_up_questions=follow_ups,
            ).model_dump()
        )

    # ============================================
    # Step 4: 运行简化版工作流 (不使用LangGraph runtime, 直接调用)
    # ============================================
    llm = get_llm()

    # 4.1 意图识别
    try:
        result = await llm.classify(
            text=req.content,
            labels=INTENT_LABELS,
            context="",
        )
        intent_type = result.get("label", "unknown")
        intent_confidence = result.get("confidence", 0.0)
    except Exception as e:
        intent_type = "unknown"
        intent_confidence = 0.0
        logger.warning(f"意图识别失败 query='{req.content}': {e}")

    logger.info(f"[意图识别] query='{req.content}' -> intent={intent_type} conf={intent_confidence:.2f}")

    # 4.2 知识库检索
    if intent_type == "knowledge_query":
        # 提取用户消息中的品牌关键词 (极目/航天/雅迅/启明/有为)
        detected_brand = None
        try:
            brand_result = await brand_service.identify_by_keyword(req.content)
            if brand_result and brand_result.confidence >= 0.8:
                detected_brand = brand_result.brand_name
        except Exception:
            pass

        matched_ids, matched_scores, method = await knowledge_service.retrieve(
            db=db,
            query=req.content,
            business_area=req.business_area,
            top_k=5,
        )

        if matched_ids and matched_scores and max(matched_scores) >= 0.4:
            # 获取最佳匹配
            best = await knowledge_service.get_knowledge_by_id(db, matched_ids[0])
            if best:
                # 品牌感知: 若该知识需要品牌(need_brand=1)
                if best.need_brand:
                    # 用户已指定品牌 → 取该品牌的同主题知识
                    if detected_brand:
                        brand_knowledge = await _get_brand_knowledge(
                            db, req.business_area, best.category_l2, detected_brand
                        )
                        if brand_knowledge:
                            best = brand_knowledge
                    else:
                        # 未指定品牌 → 追问品牌, 并列出候选
                        brand_prompt = _build_brand_prompt(best)
                        ai_msg = await session_service.add_message(
                            db=db,
                            conversation_id=conv.id,
                            role="assistant",
                            content=brand_prompt,
                            action="ask_info",
                            reply_type="brand_collection",
                            knowledge_id=best.id,
                            knowledge_code=best.knowledge_code,
                            intent_result={"intent": intent_type, "confidence": intent_confidence, "method": method},
                        )
                        # 记录待处理上下文, 下一轮据此识别用户回答的品牌
                        await session_service.set_pending_context(db, session_id, {
                            "type": "brand_collection",
                            "knowledge_id": best.id,
                            "category_l2": best.category_l2,
                        })
                        await db.commit()
                        return BaseResponse(
                            data=ChatMessageResponse(
                                session_id=session_id,
                                message_id=ai_msg.message_id,
                                seq=ai_msg.seq,
                                content=brand_prompt,
                                response_type="ask_slot",
                                need_more_info=True,
                                ask_slot_prompt="请告知设备品牌",
                                follow_up_questions=["极目(GPS+BD)", "极目单北斗(DBD)", "航天", "雅迅", "启明", "有为"],
                            ).model_dump()
                        )

                attachments = []
                if best.need_attachment:
                    for att in best.attachments:
                        attachments.append({"type": att.file_type or "link", "url": att.file_url, "name": att.file_name})

                follow_ups = _gen_follow_ups(best)

                # 受限润色: 大模型对标准答案做格式/语气优化, 不改内容
                reply_content = await _polish_answer(req.content, best)

                ai_msg = await session_service.add_message(
                    db=db,
                    conversation_id=conv.id,
                    role="assistant",
                    content=reply_content,
                    action="auto_reply",
                    reply_type="knowledge_answer",
                    knowledge_id=best.id,
                    knowledge_code=best.knowledge_code,
                    intent_result={"intent": intent_type, "confidence": intent_confidence, "brand": detected_brand, "method": method},
                )
                await session_service.update_consecutive_fail(db, session_id, increment=False)
                await db.commit()

                return BaseResponse(
                    data=ChatMessageResponse(
                        session_id=session_id,
                        message_id=ai_msg.message_id,
                        seq=ai_msg.seq,
                        content=reply_content,
                        response_type="knowledge_answer",
                        knowledge_code=best.knowledge_code,
                        attachments=attachments,
                        follow_up_questions=follow_ups,
                        evaluation_prompt="这个回答有帮助吗?",
                    ).model_dump()
                )

    # 4.3 查询意图
    if intent_type == "live_query":
        from app.nodes.query_judgment import _match_query_type
        from app.integrations.platform_client import platform_client

        qtype = _match_query_type(req.content)

        # 先尝试从用户消息提取 VIN (运营平台接口仅支持 VIN 查询)
        vin = _extract_vin(req.content)

        if qtype and vin:
            # 有 VIN → 调运营平台接口实时查询
            device = await platform_client.query_device_by_vin(vin)
            if device:
                lines = ["已为您查询到以下设备信息:"]
                field_labels = {
                    "plate_number": "车牌号",
                    "terminal_id": "记录仪设备号",
                    "service_expiry": "到期时间",
                    "vin": "车架号(VIN)",
                }
                for f, label in field_labels.items():
                    val = device.get(f)
                    if val:
                        lines.append(f"• {label}: {val}")
                content = "\n".join(lines)
                reply_type = "query_result"
            else:
                content = "未查询到该 VIN 对应的设备信息。请确认车架号(VIN)是否正确, 或联系人工客服。"
                reply_type = "query_empty"

            ai_msg = await session_service.add_message(
                db=db,
                conversation_id=conv.id,
                role="assistant",
                content=content,
                action="query",
                reply_type=reply_type,
                query_type_code=qtype,
                intent_result={"intent": intent_type, "confidence": intent_confidence, "vin": vin},
            )
            await session_service.update_consecutive_fail(db, session_id, increment=False)
            await db.commit()

            return BaseResponse(
                data=ChatMessageResponse(
                    session_id=session_id,
                    message_id=ai_msg.message_id,
                    seq=ai_msg.seq,
                    content=content,
                    response_type="query_result",
                ).model_dump()
            )

        if qtype:
            # 无 VIN → 追问车架号, 并记录pending供下一轮识别VIN
            ai_msg = await session_service.add_message(
                db=db,
                conversation_id=conv.id,
                role="assistant",
                content="请提供您的车架号(VIN), 以便查询相关信息。",
                action="ask_info",
                reply_type="slot_collection",
                query_type_code=qtype,
                intent_result={"intent": intent_type, "confidence": intent_confidence},
            )
            await session_service.set_pending_context(db, session_id, {
                "type": "vin_collection",
                "query_type_code": qtype,
            })
            await db.commit()

            return BaseResponse(
                data=ChatMessageResponse(
                    session_id=session_id,
                    message_id=ai_msg.message_id,
                    seq=ai_msg.seq,
                    content=ai_msg.content,
                    response_type="ask_slot",
                    need_more_info=True,
                    ask_slot_prompt="请提供车架号(VIN)",
                ).model_dump()
            )

    # 4.4 兜底回复
    fail_count = conv.consecutive_fail or 0
    if fail_count >= 2:
        # 转人工
        await session_service.update_session_status(db, session_id, "transferred", transfer_count=(conv.transfer_count or 0) + 1)
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content="多次未能解决您的问题, 正在为您转接人工客服...",
            action="transfer",
            reply_type="handoff",
        )
        await db.commit()

        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=ai_msg.content,
                response_type="transfer",
                should_transfer=True,
            ).model_dump()
        )

    # 兜底
    await session_service.update_consecutive_fail(db, session_id, increment=True)
    ai_msg = await session_service.add_message(
        db=db,
        conversation_id=conv.id,
        role="assistant",
        content="抱歉, 我暂时无法准确理解您的问题。请尝试用更简单的方式描述, 或输入'转人工'联系人工客服。",
        action="auto_reply",
        reply_type="fallback",
        intent_result={"intent": intent_type, "confidence": intent_confidence},
    )
    await db.commit()

    return BaseResponse(
        data=ChatMessageResponse(
            session_id=session_id,
            message_id=ai_msg.message_id,
            seq=ai_msg.seq,
            content=ai_msg.content,
            response_type="fallback",
            follow_up_questions=["设备离线了怎么办?", "如何查询SIM卡号?", "转人工"],
        ).model_dump()
    )


def _extract_vin(text: str) -> Optional[str]:
    """从用户消息中提取 VIN 码

    VIN 标准: 17 位, 字符集不含 I/O/Q (避免与 1/0/0 混淆)
    返回首个匹配的大写 VIN, 未匹配返回 None
    """
    import re
    if not text:
        return None
    m = re.search(r"[A-HJ-NPR-Z0-9]{17}", text.upper())
    return m.group(0) if m else None


def _gen_follow_ups(knowledge) -> list:
    """生成追问建议"""
    category = getattr(knowledge, "category_l2", "") or ""
    if "离线" in category or "4G" in category:
        return ["如何检查SIM卡状态?", "SIM卡怎么拔插?", "设备不定位怎么处理?"]
    elif "SIM" in category or "ID" in category:
        return ["如何查询终端号?", "SIM卡号占用了怎么办?"]
    return ["还有其他问题吗?", "转人工"]


async def _get_brand_knowledge(db, business_area: str, category_l2: str, brand_name: str):
    """取指定品牌、同主题(同category_l2)的知识条目

    Args:
        category_l2: 知识二级分类 (如 "4G离线排查")
        brand_name: 用户指定的品牌名 (如 "航天")
    """
    from app.models import KnowledgeAnswer
    from sqlalchemy import select
    stmt = select(KnowledgeAnswer).where(
        KnowledgeAnswer.business_area == business_area,
        KnowledgeAnswer.status == "published",
        KnowledgeAnswer.need_brand == True,
        KnowledgeAnswer.category_l2 == category_l2,
        KnowledgeAnswer.manufacturer == brand_name,
    ).limit(1)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


def _build_brand_prompt(knowledge) -> str:
    """构建品牌追问提示语"""
    topic = getattr(knowledge, "category_l2", "") or getattr(knowledge, "standard_question", "")
    # 主题别名映射: 把内部分类名翻译成用户能理解的表述
    # (终端号=SIM卡号, 所以"查询SIM/ID方法"也覆盖终端号查询)
    topic_aliases = {
        "查询SIM/ID方法": "查询终端号/SIM卡号/ID号",
        "4G离线排查方法": "4G离线排查",
        "按键重启方法": "设备重启方法",
        "SIM卡拔插方法": "SIM卡拔插方法",
        "终端型号": "终端型号查询",
    }
    display_topic = topic_aliases.get(topic, topic)
    return (
        f"关于「{display_topic}」，不同品牌设备的处理方法不同。\n\n"
        f"请问您的设备是什么品牌？(可选择下方对应品牌)\n"
        f"• 极目(GPS+BD)\n"
        f"• 极目单北斗(DBD)\n"
        f"• 航天\n"
        f"• 雅迅\n"
        f"• 启明\n"
        f"• 有为"
    )


async def _polish_answer(query: str, knowledge) -> str:
    """获取最终回复内容 (预润色优先, 实时润色兜底)

    策略:
    1. 优先用 knowledge.polished_answer (预润色结果, 零延迟)
    2. 没有预润色时, 若 ENABLE_POLISH=true 则实时调大模型润色 standard_answer
    3. 关闭实时润色或润色失败, 返回 standard_answer 原文

    Args:
        query: 用户问题
        knowledge: KnowledgeAnswer 对象 (含 standard_answer 和 polished_answer)
    """
    # 1. 预润色优先
    polished = getattr(knowledge, "polished_answer", None)
    if polished and polished.strip():
        return polished

    # 2. 没有预润色, 看是否开启实时润色
    answer = knowledge.standard_answer
    if not settings.ENABLE_POLISH:
        return answer
    try:
        llm = get_llm()
        return await llm.polish(query, answer)
    except Exception as e:
        logger.warning(f"润色异常, 返回原文: {e}")
        return answer
