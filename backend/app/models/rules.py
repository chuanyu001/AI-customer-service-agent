# 规则关键词表
# 用于意图识别、业务路由、转人工、高风险和查询类型等规则配置。
# 注意: 这类规则不直接返回知识答案, 避免干扰语义检索。

from sqlalchemy import Boolean, Column, DateTime, Integer, JSON, String, Text, Index
from sqlalchemy.sql import func

from app.core.database import Base


class KeywordRule(Base):
    """规则关键词.

    rule_type 示例:
    - business_route
    - transfer
    - high_risk
    - unsupported_operation
    - brand_alias
    - query_intent
    - intent_hint
    """
    __tablename__ = "keyword_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_type = Column(String(64), nullable=False, index=True, comment="规则类型")
    keyword = Column(String(128), nullable=False, index=True, comment="关键词/短语")
    business_area = Column(String(32), comment="适用业务域, 空表示全局")
    target = Column(String(128), comment="目标值, 如业务域/意图/QRY编码/品牌名")
    action = Column(String(64), comment="动作, 如 route/transfer/ask_slot")
    priority = Column(Integer, default=0, index=True, comment="优先级, 大者优先")
    is_active = Column(Boolean, default=True, index=True)
    extra_metadata = Column("metadata", JSON, comment="扩展配置")
    description = Column(Text, comment="规则说明")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_keyword_rule_type_keyword", "rule_type", "keyword"),
        Index("idx_keyword_rule_area_type", "business_area", "rule_type"),
    )
