# 所有ORM模型统一导出
# 旧知识表 (knowledge_answer等) 保留作备份, 新业务分表见 dashcam.py / business_kb.py
from .knowledge import (
    KnowledgeAnswer,
    KnowledgeQuestionVariant,
    KnowledgeKeyword,
    KnowledgeAttachment,
    KnowledgeVersion,
    FAQCard,
    QueryIntentConfig,
)
from .dashcam import (
    DashcamKnowledge,
    DashcamVariant,
    DashcamKeyword,
    DashcamAttachment,
    DashcamFaqCard,
)
from .business_kb import (
    WifiKnowledge, WifiVariant, WifiKeyword, WifiFaqCard,
    DataKnowledge, DataVariant, DataKeyword, DataFaqCard,
    RefuelingKnowledge, RefuelingVariant, RefuelingKeyword, RefuelingFaqCard,
)
from .conversation import (
    Conversation,
    Message,
    AnswerFeedback,
    HandoffTicket,
    OptimizationSample,
)
from .business import (
    BrandInfo,
    BrandMapping,
    FieldDictionary,
    DeviceVehicleRelation,
    YouweiDevice,
    OperationalData,
)
from .system import SystemConfig, DataDictionary, EventLog
from .embedding import KnowledgeEmbedding
from .rules import KeywordRule


# 业务 → 知识主表模型 的路由映射 (检索/CRUD按此路由)
BUSINESS_KNOWLEDGE_MAP = {
    "dashcam": DashcamKnowledge,
    "wifi": WifiKnowledge,
    "data": DataKnowledge,
    "refueling": RefuelingKnowledge,
}

# 业务 → FAQ卡片模型 的路由映射
BUSINESS_FAQ_MAP = {
    "dashcam": DashcamFaqCard,
    "wifi": WifiFaqCard,
    "data": DataFaqCard,
    "refueling": RefuelingFaqCard,
}

# 业务 → 变体模型
BUSINESS_VARIANT_MAP = {
    "dashcam": DashcamVariant,
    "wifi": WifiVariant,
    "data": DataVariant,
    "refueling": RefuelingVariant,
}

# 业务 → 关键词模型
BUSINESS_KEYWORD_MAP = {
    "dashcam": DashcamKeyword,
    "wifi": WifiKeyword,
    "data": DataKeyword,
    "refueling": RefuelingKeyword,
}

# 业务 → 附件模型 (仅dashcam有附件, 其他业务返回None)
BUSINESS_ATTACHMENT_MAP = {
    "dashcam": DashcamAttachment,
    "wifi": None,
    "data": None,
    "refueling": None,
}

__all__ = [
    # 旧知识表 (备份)
    "KnowledgeAnswer", "KnowledgeQuestionVariant", "KnowledgeKeyword",
    "KnowledgeAttachment", "KnowledgeVersion", "FAQCard", "QueryIntentConfig",
    # 行车记录仪 (新分表)
    "DashcamKnowledge", "DashcamVariant", "DashcamKeyword", "DashcamAttachment", "DashcamFaqCard",
    # WiFi/流量/加油
    "WifiKnowledge", "WifiVariant", "WifiKeyword", "WifiFaqCard",
    "DataKnowledge", "DataVariant", "DataKeyword", "DataFaqCard",
    "RefuelingKnowledge", "RefuelingVariant", "RefuelingKeyword", "RefuelingFaqCard",
    # 路由映射
    "BUSINESS_KNOWLEDGE_MAP", "BUSINESS_FAQ_MAP", "BUSINESS_VARIANT_MAP",
    "BUSINESS_KEYWORD_MAP", "BUSINESS_ATTACHMENT_MAP",
    # 会话
    "Conversation", "Message", "AnswerFeedback", "HandoffTicket", "OptimizationSample",
    # 业务
    "BrandInfo", "BrandMapping", "FieldDictionary", "DeviceVehicleRelation", "YouweiDevice", "OperationalData",
    # 系统
    "SystemConfig", "DataDictionary", "EventLog",
    # 向量
    "KnowledgeEmbedding",
    # 规则
    "KeywordRule",
]
