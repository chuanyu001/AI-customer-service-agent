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
from app.services.rule_service import (
    detect_business_area,
    evaluate_transfer,
    is_greeting,
    needs_clarify,
    should_route_live_query,
)
from app.services.llm_understanding_service import llm_understanding_service

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

    effective_business = detect_business_area(req.content, req.business_area)

    # ============================================
    # Step 2: 构建初始 WorkflowState
    # ============================================
    initial_state: WorkflowState = {
        "query": req.content,
        "session_id": session_id,
        "user_id": req.user_id or "",
        "business_area": effective_business,
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
            # 识别到品牌 → 取该品牌、该主题的知识 (仅dashcam有品牌)
            brand_knowledge = await _get_brand_knowledge(
                db,
                pending.get("category_l2", ""),
                brand_result.brand_name,
            )
            if brand_knowledge:
                await session_service.clear_pending_context(db, session_id)
                attachments = []
                if getattr(brand_knowledge, "need_attachment", False) and hasattr(brand_knowledge, "attachments"):
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
        # 未识别出品牌 → 清除pending, 由LLM理解下游继续处理
        # LLM 会看到上下文（上一轮问了品牌），自动判断用户是"不知道品牌"要VIN
        # 还是在问一个新问题。不再用硬编码关键词猜测。
        await session_service.clear_pending_context(db, session_id)

    # ============================================
    # Step 2.6: VIN查品牌 (用户不知道品牌, 提供了VIN做两级识别)
    # ============================================
    if pending and pending.get("type") == "vin_for_brand":
        vin = _extract_vin(req.content)
        if vin:
            await session_service.clear_pending_context(db, session_id)
            category_l2 = pending.get("category_l2", "")
            # 两级品牌识别
            brand_result = await brand_service.identify_by_vin(db, vin)
            if brand_result and brand_result.brand_name:
                brand_knowledge = await _get_brand_knowledge(db, category_l2, brand_result.brand_name)
                if brand_knowledge:
                    reply_content = await _polish_answer(req.content, brand_knowledge)
                    attachments = []
                    if getattr(brand_knowledge, "need_attachment", False) and hasattr(brand_knowledge, "attachments"):
                        for att in brand_knowledge.attachments:
                            attachments.append({"type": att.file_type or "link", "url": att.file_url, "name": att.file_name})
                    ai_msg = await session_service.add_message(
                        db=db, conversation_id=conv.id, role="assistant",
                        content=reply_content, action="auto_reply", reply_type="knowledge_answer",
                        knowledge_id=brand_knowledge.id, knowledge_code=brand_knowledge.knowledge_code,
                        intent_result={"intent": "knowledge_query", "brand": brand_result.brand_name, "via": "vin_brand_lookup"},
                    )
                    await session_service.update_consecutive_fail(db, session_id, increment=False)
                    await db.commit()
                    return BaseResponse(data=ChatMessageResponse(
                        session_id=session_id, message_id=ai_msg.message_id, seq=ai_msg.seq,
                        content=reply_content, response_type="knowledge_answer",
                        knowledge_code=brand_knowledge.knowledge_code, attachments=attachments,
                        follow_up_questions=_gen_follow_ups(brand_knowledge),
                        evaluation_prompt="这个回答有帮助吗?",
                    ).model_dump())
            # 识别失败 → 提示转人工
            ai_msg = await session_service.add_message(
                db=db, conversation_id=conv.id, role="assistant",
                content="抱歉, 未能通过VIN识别出您的设备品牌。建议您输入'转人工'联系客服协助。",
                action="auto_reply", reply_type="fallback",
                intent_result={"intent": "knowledge_query", "via": "vin_brand_lookup_failed"},
            )
            await db.commit()
            return BaseResponse(data=ChatMessageResponse(
                session_id=session_id, message_id=ai_msg.message_id, seq=ai_msg.seq,
                content=ai_msg.content, response_type="fallback",
                follow_up_questions=["转人工"],
            ).model_dump())
        # 没提取到VIN → 清除pending走正常流程
        await session_service.clear_pending_context(db, session_id)

    # ============================================
    # Step 2.7: 多轮上下文 — 待处理的转人工追问
    # ============================================
    # 上一轮命中转人工类知识并追问, 本轮用户回应 → 提取关键信息后转人工
    if pending and pending.get("type") == "transfer_collection":
        await session_service.clear_pending_context(db, session_id)
        # 尝试提取用户回应中的 VIN/ICCID 等关键信息
        collected_vin = _extract_vin(req.content)
        collected_info = []
        if collected_vin:
            collected_info.append(f"车架号(VIN)={collected_vin}")
        info_str = "；".join(collected_info) if collected_info else "用户未提供VIN/ICCID"

        await session_service.update_session_status(
            db, session_id, "transferred",
            transfer_count=(conv.transfer_count or 0) + 1,
        )
        # 创建转人工工单: summary 存完整对话上下文, collected_info 存已收集信息
        await session_service.create_handoff_ticket(
            db=db,
            session_id=session_id,
            reason_type="non_customer_kb",
            reason_detail=f"命中需人工处理的知识: {pending.get('knowledge_code', '')}",
            collected_info={"query": pending.get("query", ""), "collected": info_str},
            priority="normal",
        )
        await db.commit()
        transfer_msg = (
            f"好的，已为您转接人工客服，请稍候...\n\n"
            f"转接原因：该问题需人工客服处理（{pending.get('knowledge_code', '')}）\n"
            f"用户问题：{pending.get('query', '')}\n"
            f"已收集信息：{info_str}"
        )
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content=transfer_msg,
            action="transfer",
            reply_type="handoff",
            knowledge_id=pending.get("knowledge_id"),
            knowledge_code=pending.get("knowledge_code"),
            intent_result={
                "intent": "knowledge_query",
                "via": "transfer_collection",
                "knowledge_code": pending.get("knowledge_code"),
                "collected_info": info_str,
                "reason_type": "non_customer_kb",
            },
        )
        await db.commit()
        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=transfer_msg,
                response_type="transfer",
                should_transfer=True,
                evaluation_prompt="感谢您的耐心等待, 人工客服将尽快为您服务。",
            ).model_dump()
        )

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
    # 显式转人工、高风险投诉、超权限操作 → 直接转人工。
    transfer_decision = evaluate_transfer(req.content, effective_business)
    needs_transfer = transfer_decision.should_transfer

    if needs_transfer:
        await session_service.update_session_status(
            db, session_id, "transferred",
            transfer_count=(conv.transfer_count or 0) + 1,
        )
        # 创建转人工工单: summary 存完整对话上下文(不做LLM摘要)
        await session_service.create_handoff_ticket(
            db=db,
            session_id=session_id,
            reason_type=transfer_decision.reason_type,
            reason_detail=transfer_decision.reason,
            priority=transfer_decision.priority,
        )
        await db.commit()

        transfer_msg = f"检测到您的问题需要人工处理（{transfer_decision.reason}），正在为您转接人工客服，请稍候..."
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

    if is_greeting(req.content):
        faq_cards = await knowledge_service.get_faq_cards(db, effective_business)
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
    # Step 3.5: VIN主动品牌识别 (dashcam业务, 无pending上下文)
    # ============================================
    # 用户直接发VIN (如 LFNAHUPMXT1E19383) 时, 不依赖pending上下文,
    # 主动通过VIN查询品牌, 即使会话变了也能工作
    # 仅拦截"纯VIN"消息, 避免误拦截含VIN的完整查询 (如"查设备 LFNAHUPMXT1E19383"应走live_query)
    if effective_business == "dashcam" and not pending:
        vin = _extract_vin(req.content)
        if vin:
            stripped = req.content.strip().upper()
            is_pure_vin = (stripped == vin)
            if is_pure_vin:
                try:
                    brand_result = await brand_service.identify_by_vin(db, vin)
                except Exception as e:
                    logger.warning(f"[VIN主动识别] VIN={vin} 品牌查询异常: {e}")
                    brand_result = None
                if brand_result and brand_result.brand_name:
                    ai_msg = await session_service.add_message(
                        db=db,
                        conversation_id=conv.id,
                        role="assistant",
                        content=f"已通过车架号(VIN)识别到您的设备品牌为「{brand_result.brand_name}」。请问您遇到了什么问题，我来帮您解答。",
                        action="auto_reply",
                        reply_type="brand_identified",
                        intent_result={"intent": "knowledge_query", "brand": brand_result.brand_name, "vin": vin, "via": "vin_proactive"},
                    )
                    # 记录品牌识别结果到pending, 方便后续追问时复用
                    await session_service.set_pending_context(db, session_id, {
                        "type": "brand_identified",
                        "brand_name": brand_result.brand_name,
                        "vin": vin,
                    })
                    await session_service.update_consecutive_fail(db, session_id, increment=False)
                    await db.commit()
                    return BaseResponse(
                        data=ChatMessageResponse(
                            session_id=session_id,
                            message_id=ai_msg.message_id,
                            seq=ai_msg.seq,
                            content=ai_msg.content,
                            response_type="brand_identified",
                            follow_up_questions=["设备离线了怎么办?", "如何查询SIM卡号?", "如何查看设备绑定状态?"],
                            evaluation_prompt="这个回答有帮助吗?",
                        ).model_dump()
                    )
                else:
                    logger.info(f"[VIN主动识别] VIN={vin} 未匹配到品牌, 走正常流程")

    # ============================================
    # Step 4: LLM理解 + 规则降级 (不使用LangGraph runtime, 直接调用)
    # ============================================
    # 强规则已在前面拦截。正常主路径由大模型理解真实意图、补全上下文和抽取槽位；
    # 大模型失败时 llm_understanding_service 会自动降级到当前规则识别。
    recent_messages = await session_service.get_recent_messages(
        db,
        conv.id,
        limit=settings.LLM_UNDERSTANDING_HISTORY_LIMIT,
    )
    memory = await session_service.get_memory_context(db, session_id)
    current_pending = await session_service.get_pending_context(db, session_id)
    understanding = await llm_understanding_service.understand(
        req.content,
        business_area=effective_business,
        history=recent_messages,
        pending=current_pending,
        memory=memory,
    )
    effective_business = understanding.business_area
    qtype = understanding.query_type_code
    intent_type = understanding.intent_type
    intent_confidence = understanding.confidence
    retrieval_query = understanding.rewritten_query or req.content

    logger.info(
        "[LLM理解] query='%s' -> intent=%s business=%s qtype=%s conf=%.2f method=%s rewritten='%s'",
        req.content,
        intent_type,
        effective_business,
        qtype,
        intent_confidence,
        understanding.method,
        retrieval_query,
    )

    if intent_type == "greeting":
        faq_cards = await knowledge_service.get_faq_cards(db, effective_business)
        follow_ups = [c.title for c in faq_cards[:5]]
        content = "您好! 我是AI客服助手, 请问有什么可以帮您的?"
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content=content,
            action="auto_reply",
            reply_type="greeting",
            intent_result=understanding.to_dict(),
        )
        await session_service.update_consecutive_fail(db, session_id, increment=False)
        await session_service.update_memory_context(
            db,
            session_id,
            user_query=req.content,
            assistant_reply=content,
            understanding=understanding.to_dict(),
        )
        await db.commit()

        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=content,
                response_type="greeting",
                follow_up_questions=follow_ups,
            ).model_dump()
        )

    if intent_type in {"transfer_request", "out_of_scope"}:
        reason_type = "out_of_scope" if intent_type == "out_of_scope" else "user_request"
        reason = "大模型识别该问题需要人工处理"
        await session_service.update_session_status(
            db,
            session_id,
            "transferred",
            transfer_count=(conv.transfer_count or 0) + 1,
        )
        await session_service.create_handoff_ticket(
            db=db,
            session_id=session_id,
            reason_type=reason_type,
            reason_detail=reason,
            priority="normal",
        )
        transfer_msg = f"检测到您的问题需要人工处理（{reason}），正在为您转接人工客服，请稍候..."
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content=transfer_msg,
            action="transfer",
            reply_type="handoff",
            intent_result=understanding.to_dict(),
        )
        await session_service.update_memory_context(
            db,
            session_id,
            user_query=req.content,
            assistant_reply=transfer_msg,
            understanding=understanding.to_dict(),
        )
        await db.commit()

        return BaseResponse(
            data=ChatMessageResponse(
                session_id=session_id,
                message_id=ai_msg.message_id,
                seq=ai_msg.seq,
                content=transfer_msg,
                response_type="transfer",
                should_transfer=True,
                evaluation_prompt="感谢您的耐心等待, 人工客服将尽快为您服务。",
            ).model_dump()
        )

    if intent_type == "clarify" or understanding.need_clarify:
        clarify_msg = understanding.clarify_question or await _build_clarify_prompt(
            db, retrieval_query, effective_business
        )
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content=clarify_msg,
            action="ask_info",
            reply_type="clarify",
            intent_result=understanding.to_dict(),
        )
        await session_service.update_consecutive_fail(db, session_id, increment=False)
        await session_service.update_memory_context(
            db,
            session_id,
            user_query=req.content,
            assistant_reply=clarify_msg,
            understanding=understanding.to_dict(),
        )
        await db.commit()

        return BaseResponse(data=ChatMessageResponse(
            session_id=session_id, message_id=ai_msg.message_id, seq=ai_msg.seq,
            content=clarify_msg, response_type="ask_slot", need_more_info=True,
            ask_slot_prompt=clarify_msg,
        ).model_dump())

    # 4.2 知识库检索
    if intent_type == "knowledge_query":
        # 提取用户消息中的品牌关键词 (极目/航天/雅迅/启明/有为)
        detected_brand = None
        try:
            brand_result = await brand_service.identify_by_keyword(req.content)
            if not brand_result and retrieval_query != req.content:
                brand_result = await brand_service.identify_by_keyword(retrieval_query)
            if brand_result and brand_result.confidence >= 0.8:
                detected_brand = brand_result.brand_name
        except Exception:
            pass

        matched_ids, matched_scores, method = await knowledge_service.retrieve_with_rewrite(
            db=db,
            original_query=req.content,
            rewritten_query=retrieval_query,
            business_area=effective_business,
            top_k=5,
        )

        if matched_ids and matched_scores and max(matched_scores) >= 0.4:
            # 查询太短或意图模糊时, 先追问澄清再答
            if needs_clarify(req.content, matched_scores, method):
                clarify_msg = await _build_clarify_prompt(db, req.content, effective_business)
                ai_msg = await session_service.add_message(
                    db=db, conversation_id=conv.id, role="assistant",
                    content=clarify_msg, action="ask_info", reply_type="clarify",
                    intent_result={
                        **understanding.to_dict(),
                        "intent": intent_type,
                        "method": method,
                        "via": "clarify",
                    },
                )
                await session_service.update_consecutive_fail(db, session_id, increment=False)
                await session_service.update_memory_context(
                    db,
                    session_id,
                    user_query=req.content,
                    assistant_reply=clarify_msg,
                    understanding={
                        **understanding.to_dict(),
                        "retrieval_method": method,
                    },
                )
                await db.commit()
                return BaseResponse(data=ChatMessageResponse(
                    session_id=session_id, message_id=ai_msg.message_id, seq=ai_msg.seq,
                    content=clarify_msg, response_type="ask_slot", need_more_info=True,
                    ask_slot_prompt="请详细描述您的问题",
                ).model_dump())

            # 获取最佳匹配
            best = await knowledge_service.get_knowledge_by_id(db, matched_ids[0], effective_business)
            if best:
                # 高风险知识条目不直接对客, 进入人工处理
                if getattr(best, "risk_level", "low") == "high":
                    reason = f"命中高风险知识: {best.knowledge_code}"
                    await session_service.update_session_status(
                        db, session_id, "transferred",
                        transfer_count=(conv.transfer_count or 0) + 1,
                    )
                    await session_service.create_handoff_ticket(
                        db=db,
                        session_id=session_id,
                        reason_type="risk",
                        reason_detail=reason,
                        priority="urgent",
                    )
                    ai_msg = await session_service.add_message(
                        db=db,
                        conversation_id=conv.id,
                        role="assistant",
                        content="您的问题需要人工客服进一步处理，正在为您转接人工客服，请稍候...",
                        action="transfer",
                        reply_type="handoff",
                        knowledge_id=best.id,
                        knowledge_code=best.knowledge_code,
                        intent_result={
                            **understanding.to_dict(),
                            "intent": intent_type,
                            "confidence": intent_confidence,
                            "method": method,
                            "knowledge_code": best.knowledge_code,
                        },
                    )
                    await session_service.update_memory_context(
                        db,
                        session_id,
                        user_query=req.content,
                        assistant_reply=ai_msg.content,
                        understanding={
                            **understanding.to_dict(),
                            "retrieval_method": method,
                            "knowledge_code": best.knowledge_code,
                        },
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

                # 是否对客判断: 命中转人工类知识 → 先用追问语收集信息, 下一轮转人工
                if not getattr(best, "auto_reply", True):
                    transfer_prompt = getattr(best, "transfer_prompt", "") or (
                        "这个问题需要人工客服为您处理，正在为您转接。"
                    )
                    ai_msg = await session_service.add_message(
                        db=db,
                        conversation_id=conv.id,
                        role="assistant",
                        content=transfer_prompt,
                        action="ask_info",
                        reply_type="slot_collection",
                        knowledge_id=best.id,
                        knowledge_code=best.knowledge_code,
                        intent_result={
                            **understanding.to_dict(),
                            "intent": intent_type,
                            "confidence": intent_confidence,
                            "method": method,
                            "transfer_pending": True,
                            "knowledge_code": best.knowledge_code,
                        },
                    )
                    # 记录待处理上下文, 下一轮据此转人工
                    await session_service.set_pending_context(db, session_id, {
                        "type": "transfer_collection",
                        "knowledge_id": best.id,
                        "knowledge_code": best.knowledge_code,
                        "business_area": effective_business,
                        "query": req.content,
                    })
                    await session_service.update_memory_context(
                        db,
                        session_id,
                        user_query=req.content,
                        assistant_reply=transfer_prompt,
                        understanding={
                            **understanding.to_dict(),
                            "retrieval_method": method,
                            "knowledge_code": best.knowledge_code,
                        },
                    )
                    await db.commit()
                    return BaseResponse(
                        data=ChatMessageResponse(
                            session_id=session_id,
                            message_id=ai_msg.message_id,
                            seq=ai_msg.seq,
                            content=transfer_prompt,
                            response_type="ask_slot",
                            need_more_info=True,
                            ask_slot_prompt=transfer_prompt,
                        ).model_dump()
                    )

                # 品牌感知: 仅行车记录仪有品牌追问 (need_brand字段)
                if effective_business == "dashcam" and getattr(best, "need_brand", False):
                    # 用户已指定品牌 → 取该品牌的同主题知识
                    if detected_brand:
                        brand_knowledge = await _get_brand_knowledge(
                            db, best.category_l2, detected_brand
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
                            intent_result={
                                **understanding.to_dict(),
                                "intent": intent_type,
                                "confidence": intent_confidence,
                                "method": method,
                                "knowledge_code": best.knowledge_code,
                            },
                        )
                        # 记录待处理上下文, 下一轮据此识别用户回答的品牌
                        await session_service.set_pending_context(db, session_id, {
                            "type": "brand_collection",
                            "knowledge_id": best.id,
                            "category_l2": best.category_l2,
                        })
                        await session_service.update_memory_context(
                            db,
                            session_id,
                            user_query=req.content,
                            assistant_reply=brand_prompt,
                            understanding={
                                **understanding.to_dict(),
                                "retrieval_method": method,
                                "knowledge_code": best.knowledge_code,
                            },
                        )
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
                if getattr(best, "need_attachment", False) and hasattr(best, "attachments"):
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
                    intent_result={
                        **understanding.to_dict(),
                        "intent": intent_type,
                        "confidence": intent_confidence,
                        "brand": detected_brand,
                        "method": method,
                        "knowledge_code": best.knowledge_code,
                    },
                )
                await session_service.update_consecutive_fail(db, session_id, increment=False)
                await session_service.update_memory_context(
                    db,
                    session_id,
                    user_query=req.content,
                    assistant_reply=reply_content,
                    understanding={
                        **understanding.to_dict(),
                        "retrieval_method": method,
                        "knowledge_code": best.knowledge_code,
                    },
                    slots={"brand_name": detected_brand} if detected_brand else None,
                )
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
        from app.integrations.platform_client import platform_client

        # 先尝试从用户消息提取 VIN (运营平台接口仅支持 VIN 查询)
        vin = (
            understanding.slots.get("vin")
            or _extract_vin(req.content)
            or _extract_vin(retrieval_query)
        )

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
                intent_result={
                    **understanding.to_dict(),
                    "intent": intent_type,
                    "confidence": intent_confidence,
                    "vin": vin,
                },
            )
            await session_service.update_consecutive_fail(db, session_id, increment=False)
            await session_service.update_memory_context(
                db,
                session_id,
                user_query=req.content,
                assistant_reply=content,
                understanding=understanding.to_dict(),
                slots={"vin": vin},
            )
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
                intent_result={
                    **understanding.to_dict(),
                    "intent": intent_type,
                    "confidence": intent_confidence,
                },
            )
            await session_service.set_pending_context(db, session_id, {
                "type": "vin_collection",
                "query_type_code": qtype,
            })
            await session_service.update_memory_context(
                db,
                session_id,
                user_query=req.content,
                assistant_reply=ai_msg.content,
                understanding=understanding.to_dict(),
            )
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
        # 创建转人工工单: summary 存完整对话上下文
        await session_service.create_handoff_ticket(
            db=db,
            session_id=session_id,
            reason_type="consecutive_fail",
            reason_detail=f"连续{fail_count}轮未能解决用户问题",
            priority="normal",
        )
        ai_msg = await session_service.add_message(
            db=db,
            conversation_id=conv.id,
            role="assistant",
            content="多次未能解决您的问题, 正在为您转接人工客服...",
            action="transfer",
            reply_type="handoff",
            intent_result={
                **understanding.to_dict(),
                "intent": intent_type,
                "confidence": intent_confidence,
                "via": "consecutive_fail",
            },
        )
        await session_service.update_memory_context(
            db,
            session_id,
            user_query=req.content,
            assistant_reply=ai_msg.content,
            understanding=understanding.to_dict(),
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

    # 兜底 — 意图不明确时追问, 而非直接放弃
    await session_service.update_consecutive_fail(db, session_id, increment=True)

    # 尝试从低置信向量/关键词中找候选, 生成追问
    fallback_msg = await _build_clarify_prompt(db, req.content, effective_business)

    ai_msg = await session_service.add_message(
        db=db,
        conversation_id=conv.id,
        role="assistant",
        content=fallback_msg,
        action="ask_info",
        reply_type="fallback_clarify",
        intent_result={
            **understanding.to_dict(),
            "intent": intent_type,
            "confidence": intent_confidence,
            "via": "clarify",
        },
    )
    await session_service.update_memory_context(
        db,
        session_id,
        user_query=req.content,
        assistant_reply=fallback_msg,
        understanding=understanding.to_dict(),
    )
    await db.commit()

    return BaseResponse(
        data=ChatMessageResponse(
            session_id=session_id,
            message_id=ai_msg.message_id,
            seq=ai_msg.seq,
            content=ai_msg.content,
            response_type="fallback",
            follow_up_questions=["转人工"],
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


def _needs_clarify(query: str, scores: list, method: str) -> bool:
    """兼容旧测试入口, 实际逻辑在 rule_service.needs_clarify."""
    return needs_clarify(query, scores, method)

def _detect_business_area(text: str, fallback: str) -> str:
    """兼容旧测试入口, 实际逻辑在 rule_service.detect_business_area."""
    return detect_business_area(text, fallback)

def _should_route_live_query(text: str, query_type_code: str) -> bool:
    """兼容旧测试入口, 实际逻辑在 rule_service.should_route_live_query."""
    return should_route_live_query(text, query_type_code)


async def _build_clarify_prompt(db, query: str, business_area: str) -> str:
    """意图不明时, 从低置信候选生成追问, 引导用户澄清需求."""
    try:
        from app.models import BUSINESS_KNOWLEDGE_MAP
        from sqlalchemy import select

        # 取低置信向量候选生成澄清问题; 不再使用知识关键词表做候选。
        try:
            from app.services.embedding_service import embedding_service
            vec_results = await embedding_service.search(query, business_area=business_area, top_k=3)
            vec_ids = [kid for kid, _ in vec_results]
        except Exception:
            vec_ids = []

        all_ids = list(dict.fromkeys(vec_ids))[:3]
        if not all_ids:
            return ("抱歉，我没有完全理解您的问题。您能再具体描述一下吗？\n"
                    "比如告诉我您遇到的问题是什么、涉及到什么设备或服务。\n"
                    "如需人工协助，请输入转人工。")

        # 取候选的标准问题
        kn_model = BUSINESS_KNOWLEDGE_MAP.get(business_area)
        result = await db.execute(
            select(kn_model.standard_question).where(kn_model.id.in_(all_ids))
        )
        candidates = [r[0] for r in result.all()]

        if len(candidates) >= 2:
            return f"我理解您想了解：\n① {candidates[0]}\n② {candidates[1]}\n\n请问您指的是哪一个？或者您可以直接描述您遇到的问题。"
        elif candidates:
            return f"我理解您想问的和「{candidates[0]}」有关吗？请确认一下，或者告诉我更多细节。"
        else:
            return "抱歉，我没有完全理解您的问题。您能再具体描述一下吗？比如告诉我您遇到的问题是什么、涉及到什么设备或服务。\n\n如需人工协助，请输入转人工。"
    except Exception:
        return "抱歉，我没有完全理解您的问题。您能再具体描述一下吗？\n\n如需人工协助，请输入转人工。"


def _gen_follow_ups(knowledge) -> list:
    """生成追问建议 (兼容dashcam的category_l2和其他业务的category)"""
    category = getattr(knowledge, "category_l2", "") or getattr(knowledge, "category", "") or ""
    if "离线" in category or "4G" in category:
        return ["如何检查SIM卡状态?", "SIM卡怎么拔插?", "设备不定位怎么处理?"]
    elif "SIM" in category or "ID" in category:
        return ["如何查询终端号?", "SIM卡号占用了怎么办?"]
    return ["还有其他问题吗?", "转人工"]


async def _get_brand_knowledge(db, category_l2: str, brand_name: str):
    """取指定品牌、同主题(同category_l2)的行车记录仪知识条目

    Args:
        category_l2: 知识二级分类 (如 "4G离线排查方法")
        brand_name: 用户指定的品牌名 (如 "航天")
    """
    from app.models import DashcamKnowledge
    from sqlalchemy import select
    stmt = select(DashcamKnowledge).where(
        DashcamKnowledge.status == "published",
        DashcamKnowledge.need_brand == True,
        DashcamKnowledge.category_l2 == category_l2,
        DashcamKnowledge.manufacturer == brand_name,
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
