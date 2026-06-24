# WiFi/基础流量/折扣加油 知识库 ORM 模型 (纯问答, 精简字段)
# 三业务结构同构, 用 mixin 复用列定义, 显式声明类避免注册名冲突
#
# 每业务含4张表: {prefix}_knowledge / _variant / _keyword / _faq_card
# 精简字段: 无 manufacturer/need_attachment/关联查询编号 (三业务纯问答用不到)
# 保留 need_brand_route: WiFi的WF0008车系路由标记

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, ForeignKey
)
from sqlalchemy.orm import relationship, declared_attr
from sqlalchemy.sql import func
from app.core.database import Base


class BusinessKnowledgeMixin:
    """三业务知识主表的公共列 (不含主键和表名, 子类各自声明)"""
    knowledge_code = Column(String(64), unique=True, index=True, nullable=False, comment="知识编码")
    category = Column(String(64), comment="知识类型 (注册与要求/套餐与价格...)")
    standard_question = Column(String(512), nullable=False, comment="标准问题")
    common_phrasings = Column(Text, comment="常见问法 (分号分隔)")
    standard_answer = Column(Text, nullable=False, comment="标准回答")
    polished_answer = Column(Text, comment="润色答案(预计算)")
    reference_url = Column(String(512), comment="参考链接")
    need_brand_route = Column(Boolean, default=False, comment="车系路由标记")
    auto_reply = Column(Boolean, default=True, comment="是否对客自动回复(对客=True/转人工=False)")
    transfer_prompt = Column(Text, comment="转人工前追问语(对客类为空)")
    status = Column(String(32), default="published", comment="状态")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================
# WiFi套餐
# ============================================
class WifiKnowledge(BusinessKnowledgeMixin, Base):
    __tablename__ = "wifi_knowledge"
    id = Column(Integer, primary_key=True, autoincrement=True)
    variants = relationship("WifiVariant", back_populates="knowledge", cascade="all, delete-orphan")
    keywords = relationship("WifiKeyword", back_populates="knowledge", cascade="all, delete-orphan")


class WifiVariant(Base):
    __tablename__ = "wifi_variant"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("wifi_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_text = Column(String(512), nullable=False, index=True, comment="问法变体")
    source = Column(String(32), default="import")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("WifiKnowledge", back_populates="variants")


class WifiKeyword(Base):
    __tablename__ = "wifi_keyword"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("wifi_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True, comment="关键词")
    weight = Column(Integer, default=1, comment="权重")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("WifiKnowledge", back_populates="keywords")


class WifiFaqCard(Base):
    __tablename__ = "wifi_faq_card"
    id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(64), unique=True, index=True, nullable=False, comment="卡片编码")
    title = Column(String(256), nullable=False, comment="卡片标题")
    knowledge_id = Column(Integer, ForeignKey("wifi_knowledge.id", ondelete="SET NULL"), comment="关联知识ID")
    category = Column(String(64), comment="分类")
    display_order = Column(Integer, default=0, comment="显示顺序")
    is_active = Column(Boolean, default=True, comment="是否启用")
    click_count = Column(Integer, default=0, comment="点击量")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================
# 基础流量
# ============================================
class DataKnowledge(BusinessKnowledgeMixin, Base):
    __tablename__ = "data_knowledge"
    id = Column(Integer, primary_key=True, autoincrement=True)
    variants = relationship("DataVariant", back_populates="knowledge", cascade="all, delete-orphan")
    keywords = relationship("DataKeyword", back_populates="knowledge", cascade="all, delete-orphan")


class DataVariant(Base):
    __tablename__ = "data_variant"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("data_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_text = Column(String(512), nullable=False, index=True, comment="问法变体")
    source = Column(String(32), default="import")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("DataKnowledge", back_populates="variants")


class DataKeyword(Base):
    __tablename__ = "data_keyword"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("data_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True, comment="关键词")
    weight = Column(Integer, default=1, comment="权重")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("DataKnowledge", back_populates="keywords")


class DataFaqCard(Base):
    __tablename__ = "data_faq_card"
    id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(64), unique=True, index=True, nullable=False, comment="卡片编码")
    title = Column(String(256), nullable=False, comment="卡片标题")
    knowledge_id = Column(Integer, ForeignKey("data_knowledge.id", ondelete="SET NULL"), comment="关联知识ID")
    category = Column(String(64), comment="分类")
    display_order = Column(Integer, default=0, comment="显示顺序")
    is_active = Column(Boolean, default=True, comment="是否启用")
    click_count = Column(Integer, default=0, comment="点击量")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================
# 折扣加油
# ============================================
class RefuelingKnowledge(BusinessKnowledgeMixin, Base):
    __tablename__ = "refueling_knowledge"
    id = Column(Integer, primary_key=True, autoincrement=True)
    variants = relationship("RefuelingVariant", back_populates="knowledge", cascade="all, delete-orphan")
    keywords = relationship("RefuelingKeyword", back_populates="knowledge", cascade="all, delete-orphan")


class RefuelingVariant(Base):
    __tablename__ = "refueling_variant"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("refueling_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_text = Column(String(512), nullable=False, index=True, comment="问法变体")
    source = Column(String(32), default="import")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("RefuelingKnowledge", back_populates="variants")


class RefuelingKeyword(Base):
    __tablename__ = "refueling_keyword"
    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("refueling_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True, comment="关键词")
    weight = Column(Integer, default=1, comment="权重")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    knowledge = relationship("RefuelingKnowledge", back_populates="keywords")


class RefuelingFaqCard(Base):
    __tablename__ = "refueling_faq_card"
    id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(64), unique=True, index=True, nullable=False, comment="卡片编码")
    title = Column(String(256), nullable=False, comment="卡片标题")
    knowledge_id = Column(Integer, ForeignKey("refueling_knowledge.id", ondelete="SET NULL"), comment="关联知识ID")
    category = Column(String(64), comment="分类")
    display_order = Column(Integer, default=0, comment="显示顺序")
    is_active = Column(Boolean, default=True, comment="是否启用")
    click_count = Column(Integer, default=0, comment="点击量")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
