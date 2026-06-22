# 节点6: 回复生成
# 根据 response_type 生成不同类型的回复

from typing import List, Dict, Optional
from ..graph.state import WorkflowState
from ..services.knowledge_service import knowledge_service


async def response_generation_node(state: WorkflowState) -> WorkflowState:
    """回复生成节点

    根据 response_type 生成回复:
    - knowledge_answer: 标准知识回答 + 附件 + 追问建议
    - query_result: 查询结果格式化
    - ask_slot: 槽位追问
    - transfer: 转人工过渡语
    - greeting: 欢迎语 + FAQ卡片
    - fallback: 兜底回复

    同时检查 consecutive_fail_count → 标记是否转人工
    """
    intent_type = state.get("intent_type", "unknown")

    # ============================================
    # 路由: 根据意图类型决定回复策略
    # ============================================
    if intent_type == "transfer_request":
        _build_transfer_response(state)
    elif intent_type == "greeting":
        _build_greeting_response(state)
    elif intent_type == "knowledge_query":
        _build_knowledge_response(state)
    elif intent_type == "live_query":
        _build_query_response(state)
    else:
        _build_fallback_response(state)

    # ============================================
    # 转人工判断
    # ============================================
    consecutive_fail = state.get("consecutive_fail_count", 0)
    max_fail = 3  # 可从 system_config 读取

    if consecutive_fail >= max_fail:
        state["should_transfer"] = True
        state["transfer_reason_type"] = "consecutive_fail"
        state["transfer_reason"] = f"连续{consecutive_fail}轮未能解决用户问题"

    return state


async def response_generation_with_db(state: WorkflowState, db) -> WorkflowState:
    """带数据库会话的回复生成 (实际调用入口)"""
    intent_type = state.get("intent_type", "unknown")

    if intent_type == "transfer_request":
        _build_transfer_response(state)
    elif intent_type == "greeting":
        await _build_greeting_with_db(state, db)
    elif intent_type == "knowledge_query":
        await _build_knowledge_with_db(state, db)
    elif intent_type == "live_query":
        await _build_query_with_db(state, db)
    else:
        _build_fallback_response(state)

    # 转人工判断
    consecutive_fail = state.get("consecutive_fail_count", 0)
    if consecutive_fail >= 3:
        state["should_transfer"] = True
        state["transfer_reason_type"] = "consecutive_fail"
        state["transfer_reason"] = f"连续{consecutive_fail}轮未能解决用户问题"

    return state


# ============================================
# 回复构建函数
# ============================================

def _build_knowledge_response(state: WorkflowState):
    """构建知识问答回复"""
    matched_ids = state.get("matched_knowledge_ids", [])
    matched_scores = state.get("matched_knowledge_scores", [])

    if matched_ids and matched_scores and max(matched_scores) >= 0.4:
        # 有匹配的知识 (实际内容由调用方从DB填充)
        state["response_type"] = "knowledge_answer"
        state["final_response"] = None  # 由调用方填充
        state["consecutive_fail_count"] = 0  # 匹配成功, 重置计数
    else:
        _build_fallback_response(state)


async def _build_knowledge_with_db(state: WorkflowState, db):
    """带DB的知识回复构建"""
    matched_ids = state.get("matched_knowledge_ids", [])
    matched_scores = state.get("matched_knowledge_scores", [])

    if matched_ids and matched_scores and max(matched_scores) >= 0.4:
        # 获取最佳匹配的知识
        best_id = matched_ids[0]
        knowledge = await knowledge_service.get_knowledge_by_id(db, best_id)

        if knowledge:
            state["response_type"] = "knowledge_answer"
            state["final_response"] = knowledge.standard_answer

            # 附件
            attachments = []
            if knowledge.need_attachment:
                for att in knowledge.attachments:
                    attachments.append({
                        "type": att.file_type or "link",
                        "url": att.file_url,
                        "name": att.file_name,
                    })
            state["response_attachments"] = attachments

            # 追问建议
            follow_ups = _generate_follow_ups(knowledge)
            state["follow_up_questions"] = follow_ups

            state["consecutive_fail_count"] = 0
            return

    _build_fallback_response(state)


def _build_query_response(state: WorkflowState):
    """构建查询结果回复"""
    query_result = state.get("query_result")
    is_live_query = state.get("is_live_query", False)
    slots_collected = state.get("slots_collected", False)

    if not is_live_query:
        _build_fallback_response(state)
    elif not slots_collected:
        # 需要追问槽位
        state["response_type"] = "ask_slot"
        state["final_response"] = state.get("ask_slot_prompt", "请提供更多信息以便查询")
    elif query_result:
        # 有查询结果
        state["response_type"] = "query_result"
        state["consecutive_fail_count"] = 0
    else:
        # 查询无结果
        state["response_type"] = "query_result"
        state["final_response"] = "未查询到相关设备信息。请确认您提供的信息是否正确, 或联系人工客服。"


async def _build_query_with_db(state: WorkflowState, db):
    """带DB的查询回复构建"""
    query_result = state.get("query_result")
    is_live_query = state.get("is_live_query", False)
    slots_collected = state.get("slots_collected", False)
    query_type_code = state.get("query_type_code", "")

    if not is_live_query:
        _build_fallback_response(state)
    elif not slots_collected:
        state["response_type"] = "ask_slot"
        state["final_response"] = state.get("ask_slot_prompt", "请提供更多信息以便查询")
    elif query_result:
        # 获取回复模板
        from app.models import QueryIntentConfig
        from sqlalchemy import select
        stmt = select(QueryIntentConfig).where(
            QueryIntentConfig.query_type_code == query_type_code
        )
        result = await db.execute(stmt)
        config = result.scalar_one_or_none()

        template = config.reply_template_normal if config else ""
        from ..nodes.database_query import format_query_result
        state["final_response"] = format_query_result(query_result, template)
        state["response_type"] = "query_result"
        state["consecutive_fail_count"] = 0
    else:
        state["response_type"] = "query_result"
        state["final_response"] = "未查询到相关设备信息。请确认您提供的信息是否正确, 或联系人工客服。"


def _build_transfer_response(state: WorkflowState):
    """构建转人工回复"""
    state["response_type"] = "transfer"
    state["final_response"] = "正在为您转接人工客服, 请稍候..."
    state["should_transfer"] = True
    state["transfer_reason_type"] = state.get("transfer_reason_type", "user_request")
    state["transfer_reason"] = state.get("transfer_reason", "用户要求转人工")


def _build_greeting_response(state: WorkflowState):
    """构建欢迎语回复"""
    state["response_type"] = "greeting"
    state["final_response"] = "您好! 我是AI客服助手, 请问有什么可以帮您的?"
    state["consecutive_fail_count"] = 0
    state["follow_up_questions"] = [
        "设备离线了怎么办?",
        "如何查询SIM卡号和终端号?",
        "设备怎么重启?",
    ]


async def _build_greeting_with_db(state: WorkflowState, db):
    """带DB的欢迎语回复"""
    state["response_type"] = "greeting"
    state["final_response"] = "您好! 我是AI客服助手, 请问有什么可以帮您的?"

    # 获取FAQ卡片
    faq_cards = await knowledge_service.get_faq_cards(db, state.get("business_area", "dashcam"))
    state["follow_up_questions"] = [card.title for card in faq_cards[:5]]

    state["consecutive_fail_count"] = 0


def _build_fallback_response(state: WorkflowState):
    """构建兜底回复"""
    fail_count = state.get("consecutive_fail_count", 0)
    state["response_type"] = "fallback"

    if fail_count <= 1:
        state["final_response"] = (
            "抱歉, 我暂时无法准确理解您的问题。\n\n"
            "您可以尝试:\n"
            "1. 用更简单的方式描述问题\n"
            "2. 选择下方常见问题\n"
            "3. 输入'转人工'联系人工客服"
        )
        state["follow_up_questions"] = [
            "设备离线了怎么办?",
            "如何查询SIM卡号?",
            "转人工",
        ]
    else:
        state["final_response"] = (
            "我仍然无法准确理解您的问题。\n\n"
            "建议您转人工客服获取帮助, 输入'转人工'即可。"
        )
        state["follow_up_questions"] = ["转人工"]


def _generate_follow_ups(knowledge) -> List[str]:
    """生成追问建议"""
    follow_ups = []
    category = getattr(knowledge, "category_l2", "") or ""

    if "离线" in category or "4G" in category:
        follow_ups = [
            "如何检查SIM卡状态?",
            "SIM卡怎么拔插?",
            "设备不定位怎么处理?",
        ]
    elif "SIM" in category or "ID" in category:
        follow_ups = [
            "如何查询终端号?",
            "SIM卡号占用了怎么办?",
        ]
    else:
        follow_ups = [
            "还有其他问题吗?",
            "转人工",
        ]

    return follow_ups
