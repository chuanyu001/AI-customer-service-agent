# 节点1: 消息预处理
# 清洗输入、识别消息类型、上下文继承

import re
from ..graph.state import WorkflowState


# 转人工关键词
TRANSFER_KEYWORDS = [
    "转人工", "人工客服", "人工服务", "找人工", "真人",
    "转接", "人工电话", "我要找客服", "人工", "客服",
]

# 问候语
GREETING_PATTERNS = [
    r"^(你好|您好|hi|hello|在吗|在不在|嗨|早上好|下午好|晚上好)",
]


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
    if not text:
        return ""

    # 去首尾空白
    text = text.strip()

    # 统一换行
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 统一省略号
    text = text.replace("…", "...").replace("。。", "。")

    # 去除多余空格
    text = re.sub(r"\s+", " ", text)

    return text


def check_transfer_keyword(text: str) -> bool:
    """检测是否包含转人工关键词"""
    for kw in TRANSFER_KEYWORDS:
        if kw in text:
            return True
    return False


def check_greeting(text: str) -> bool:
    """检测是否为问候语"""
    for pattern in GREETING_PATTERNS:
        if re.match(pattern, text):
            return True
    return False
