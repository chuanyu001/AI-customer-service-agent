# 节点7: 转人工判断 + 日志/评价/工单
# 5种转人工触发条件 + 对话摘要 + 工单生成

from datetime import datetime
from typing import Optional
from ..graph.state import WorkflowState
from ..services.llm_service import get_llm


# 高风险关键词
HIGH_RISK_KEYWORDS = [
    "投诉", "退款", "315", "12315", "起诉", "媒体曝光",
    "曝光", "维权", "消协", "工商", "赔偿", "欺诈", "骗人",
]

# 超出AI范围的操作
UNSUPPORTED_OPERATIONS = [
    "审核", "转网", "入网审核", "开通审核",
    "写车架号", "下发车架号", "车辆信息写入",
    "修改车辆资料", "修改设备资料",
    "修改绑定", "换绑", "解绑",
    "激活设备", "修改套餐", "修改缴费记录",
]


async def human_transfer_node(state: WorkflowState) -> WorkflowState:
    """转人工判断 + 日志/评价/工单节点

    5种转人工触发条件:
    1. consecutive_fail: 连续3轮未解决
    2. keyword: 高风险关键词
    3. user_request: 用户明确要求
    4. out_of_scope: 超出AI服务范围
    5. risk: 知识条目标记为高风险

    处理内容:
    - 生成AI对话摘要
    - 收集已获取的业务信息
    - 非工作时间 → 引导留联系方式
    - 生成工单
    """
    should_transfer = state.get("should_transfer", False)
    transfer_reason_type = state.get("transfer_reason_type", "")

    # ============================================
    # Step 1: 检查5种转人工条件
    # ============================================

    if not should_transfer:
        should_transfer, reason_type, reason = _evaluate_transfer(state)
        if should_transfer:
            state["should_transfer"] = True
            state["transfer_reason_type"] = reason_type
            state["transfer_reason"] = reason
            transfer_reason_type = reason_type

    if not should_transfer:
        # 不需要转人工 → 添加评价引导
        state["evaluation_prompt"] = "这个回答有帮助吗?"
        return state

    # ============================================
    # Step 2: 生成对话摘要
    # ============================================
    messages = state.get("messages", [])
    if messages:
        try:
            conversation_text = _format_conversation(messages)
            llm = get_llm()
            summary = await llm.summarize(conversation_text, max_length=200)
            state["transfer_summary"] = summary
        except Exception:
            state["transfer_summary"] = _simple_summary(messages, state)
    else:
        state["transfer_summary"] = f"用户问题: {state.get('query', '')}"

    # ============================================
    # Step 3: 非工作时间处理
    # ============================================
    if _is_off_hours():
        state["final_response"] = (
            "当前为非工作时间, 人工客服暂时不在线。\n\n"
            "请描述您的问题并留下联系方式, 我们将在工作时间尽快回复您。\n\n"
            "💡 您也可以先查看常见问题, 或等待工作时间再联系。"
        )
        state["transfer_priority"] = "normal"
    else:
        state["final_response"] = (
            f"正在为您转接人工客服, 请稍候...\n\n"
            f"转接原因: {state.get('transfer_reason', '用户请求')}\n"
            f"预计等待时间: 请留意客服消息通知"
        )
        # 根据原因类型确定优先级
        priority_map = {
            "risk": "urgent",
            "user_request": "normal",
            "consecutive_fail": "normal",
            "out_of_scope": "normal",
            "keyword": "high",
        }
        state["transfer_priority"] = priority_map.get(transfer_reason_type, "normal")

    # ============================================
    # Step 4: 设置响应
    # ============================================
    state["response_type"] = "transfer"
    state["follow_up_questions"] = []
    state["evaluation_prompt"] = "感谢您的耐心等待, 人工客服将尽快为您服务。"

    return state


def _evaluate_transfer(state: WorkflowState) -> tuple:
    """评估是否需要转人工 → (should_transfer, reason_type, reason)"""
    query = state.get("query", "")
    consecutive_fail = state.get("consecutive_fail_count", 0)

    # Rule 1: 连续失败
    if consecutive_fail >= 3:
        return True, "consecutive_fail", f"连续{consecutive_fail}轮未能解决用户问题"

    # Rule 2: 高风险关键词
    for kw in HIGH_RISK_KEYWORDS:
        if kw in query:
            return True, "risk", f"检测到高风险关键词: {kw}"

    # Rule 3: 用户请求 (由 intent_recognition 处理)
    if state.get("intent_type") == "transfer_request":
        return True, "user_request", "用户明确要求转人工"

    # Rule 4: 超出范围操作
    for op in UNSUPPORTED_OPERATIONS:
        if op in query:
            return True, "out_of_scope", f"用户请求超出AI服务范围: {op}"

    return False, "", ""


def _is_off_hours() -> bool:
    """判断当前是否非工作时间"""
    now = datetime.now()
    # 周末
    if now.weekday() >= 5:
        return True
    # 工作时段外
    hour = now.hour
    if hour < 9 or hour >= 18:
        return True
    return False


def _format_conversation(messages: list) -> str:
    """格式化对话为文本"""
    lines = []
    for msg in messages[-10:]:  # 最近10条
        role = getattr(msg, "type", "unknown") if hasattr(msg, "type") else "unknown"
        content = getattr(msg, "content", str(msg)) if hasattr(msg, "content") else str(msg)
        role_label = "用户" if role in ("user", "human") else "客服"
        lines.append(f"{role_label}: {content[:200]}")
    return "\n".join(lines)


def _simple_summary(messages: list, state: WorkflowState) -> str:
    """简单摘要 (不调用LLM)"""
    query = state.get("query", "")
    intent = state.get("intent_type", "unknown")
    intent_map = {
        "knowledge_query": "知识问答",
        "live_query": "数据查询",
        "transfer_request": "要求转人工",
        "greeting": "问候",
        "unknown": "未识别",
    }
    return f"用户咨询: {query[:100]} (意图: {intent_map.get(intent, intent)})"
