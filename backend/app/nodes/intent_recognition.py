# 节点2: 意图识别 + 问题改写
# LLM分类 + 关键词快速通道 + 多轮问题改写

import json
from ..graph.state import WorkflowState
from ..services.llm_service import get_llm
from ..nodes.preprocess import check_transfer_keyword, check_greeting


# 意图标签
INTENT_LABELS = [
    "knowledge_query",      # 固定知识问答
    "live_query",           # 需要查询运营平台数据库
    "transfer_request",     # 明确要求转人工
    "greeting",             # 问候语
    "unknown",              # 无法识别
]

# 意图中文说明 (用于LLM prompt)
INTENT_DESCRIPTIONS = {
    "knowledge_query": "固定知识问答 (操作指引/故障排查/设备信息/驾驶监控/通用知识)",
    "live_query": "需要查询运营平台实时数据 (SIM卡号/终端号/在线状态/服务商/套餐等)",
    "transfer_request": "用户明确要求转人工客服",
    "greeting": "问候语/寒暄",
    "unknown": "无法识别意图",
}


async def intent_recognition_node(state: WorkflowState) -> WorkflowState:
    """意图识别 + 问题改写节点

    处理流程:
    1. 关键词快速通道 (转人工 / 问候语)
    2. LLM意图分类
    3. 问题改写 (多轮上下文补全)
    """
    query = state.get("cleaned_query", state.get("query", ""))
    llm = get_llm()

    # ============================================
    # Step 1: 关键词快速通道 (不调用LLM)
    # ============================================

    # 转人工关键词检测
    if check_transfer_keyword(query):
        state["intent_type"] = "transfer_request"
        state["intent_confidence"] = 0.99
        state["rewritten_query"] = query
        return state

    # 问候语检测
    if check_greeting(query):
        state["intent_type"] = "greeting"
        state["intent_confidence"] = 0.95
        state["rewritten_query"] = query
        return state

    # ============================================
    # Step 2: LLM意图分类
    # ============================================

    # 构建历史上下文
    messages = state.get("messages", [])
    history_text = _build_history_context(messages, max_turns=3)

    try:
        result = await llm.classify(
            text=query,
            labels=INTENT_LABELS,
            context=history_text,
        )
        intent_type = result.get("label", "unknown")
        confidence = result.get("confidence", 0.0)
    except Exception as e:
        # LLM调用失败 → 降级为 unknown
        intent_type = "unknown"
        confidence = 0.0
        state["error"] = f"意图识别LLM调用失败: {e}"

    state["intent_type"] = intent_type
    state["intent_confidence"] = confidence

    # ============================================
    # Step 3: 问题改写 (多轮上下文补全)
    # ============================================

    if history_text and intent_type in ("knowledge_query", "live_query", "unknown"):
        try:
            history_lines = _extract_history_lines(messages, max_turns=3)
            rewritten = await llm.rewrite(query, history_lines)
            if rewritten and rewritten != query:
                state["rewritten_query"] = rewritten
            else:
                state["rewritten_query"] = query
        except Exception:
            state["rewritten_query"] = query
    else:
        state["rewritten_query"] = query

    return state


def _build_history_context(messages: list, max_turns: int = 3) -> str:
    """构建对话历史上下文 (用于LLM分类)"""
    if not messages:
        return ""

    # 取最近N轮对话
    recent = []
    for msg in messages[-max_turns * 2:]:  # 每轮=user+assistant
        role = getattr(msg, "type", "unknown") if hasattr(msg, "type") else "unknown"
        content = getattr(msg, "content", str(msg)) if hasattr(msg, "content") else str(msg)
        role_label = "用户" if role in ("user", "human") else "客服"
        recent.append(f"{role_label}: {content[:100]}")

    return "\n".join(recent)


def _extract_history_lines(messages: list, max_turns: int = 3) -> list:
    """提取历史消息文本行"""
    if not messages:
        return []

    lines = []
    for msg in messages[-max_turns * 2:]:
        content = getattr(msg, "content", str(msg)) if hasattr(msg, "content") else str(msg)
        lines.append(content[:200])

    return lines
