# 所有ORM模型统一导出
from .knowledge import (
    KnowledgeAnswer,
    KnowledgeQuestionVariant,
    KnowledgeKeyword,
    KnowledgeAttachment,
    KnowledgeVersion,
    FAQCard,
    QueryIntentConfig,
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
    OperationalDevice,
    DeviceVehicleRelation,
)
from .system import SystemConfig, DataDictionary, EventLog
from .embedding import KnowledgeEmbedding

__all__ = [
    # 知识库
    "KnowledgeAnswer",
    "KnowledgeQuestionVariant",
    "KnowledgeKeyword",
    "KnowledgeAttachment",
    "KnowledgeVersion",
    "FAQCard",
    "QueryIntentConfig",
    # 会话
    "Conversation",
    "Message",
    "AnswerFeedback",
    "HandoffTicket",
    "OptimizationSample",
    # 业务
    "BrandInfo",
    "BrandMapping",
    "FieldDictionary",
    "OperationalDevice",
    "DeviceVehicleRelation",
    # 系统
    "SystemConfig",
    "DataDictionary",
    "EventLog",
    # 向量
    "KnowledgeEmbedding",
]
