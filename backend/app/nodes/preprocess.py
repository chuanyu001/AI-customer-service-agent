# 节点1: 消息预处理
# 清洗输入、识别消息类型、上下文继承

from ..graph.state import WorkflowState
from ..services.rule_service import (
    TRANSFER_KEYWORDS,
    normalize_text,
    is_greeting,
    is_transfer_request,
)


async def preprocess_node(state: WorkflowState) -> WorkflowState:
    """消息预处理节点

    处理内容:
    1. 清洗输入 (去空白、统一标点)
    2. 识别消息类型
    3. 从历史消息继承 collected_slots
    4. 递增 dialogue_round
    5. 快速检测转人工关键词和问候语
    """
    query = state.get("query", "")

    # 1. 清洗
    cleaned = _clean_query(query)
    state["cleaned_query"] = cleaned
    state["query"] = cleaned  # 更新原始query

    # 2. 消息类型
    message_type = state.get("message_type", "text")
    if not message_type or message_type not in ("text", "image", "voice", "video"):
        message_type = "text"
    state["message_type"] = message_type

    # 3. 继承上下文
    if "collected_slots" not in state:
        state["collected_slots"] = {}
    if "dialogue_round" not in state:
        state["dialogue_round"] = 0
    if "consecutive_fail_count" not in state:
        state["consecutive_fail_count"] = 0

    state["dialogue_round"] += 1

    # 4. 业务领域默认值
    if not state.get("business_area"):
        state["business_area"] = "dashcam"

    # 5. 初始化响应字段
    state["response_type"] = "fallback"
    state["response_attachments"] = []
    state["follow_up_questions"] = []
    state["should_transfer"] = False
    state["error"] = None
    state["metadata"] = state.get("metadata", {})

    return state


def _clean_query(text: str) -> str:
    """清洗用户输入"""
    return normalize_text(text)


def check_transfer_keyword(text: str) -> bool:
    """检测是否包含转人工关键词"""
    return is_transfer_request(text)


def check_greeting(text: str) -> bool:
    """检测是否为问候语"""
    return is_greeting(text)
