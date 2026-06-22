# 知识库 ORM 模型
# 知识数据表组: knowledge_answer, question_variant, keyword, attachment, version, faq_card, query_intent_config

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class KnowledgeAnswer(Base):
    """知识问答主表 (对应Excel 01_知识问答库, 144条)"""
    __tablename__ = "knowledge_answer"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_code = Column(String(64), unique=True, index=True, nullable=False, comment="知识唯一编码")
    business_area = Column(String(32), nullable=False, default="dashcam", comment="业务领域: dashcam/wifi/data/refueling")
    category_l1 = Column(String(64), comment="一级分类 (故障排查/设备信息/操作指引...)")
    category_l2 = Column(String(64), comment="二级分类 (4G离线/查询SIM/按键重启...)")
    manufacturer = Column(String(128), comment="适用厂商 (通用/极目/航天/雅迅/启明/有为)")
    standard_question = Column(String(512), nullable=False, comment="标准问题")
    standard_answer = Column(Text, nullable=False, comment="标准回答")
    answer_type = Column(String(32), default="text", comment="回答类型: text/video/image/mixed")
    need_brand = Column(Boolean, default=False, comment="是否需要品牌识别 (123/144=1)")
    need_attachment = Column(Boolean, default=False, comment="是否需要附件 (15/144=1)")
    risk_level = Column(String(16), default="low", comment="风险等级: low/medium/high")
    auto_reply = Column(Boolean, default=True, comment="是否允许自动回复")
    transfer_condition = Column(Text, comment="转人工条件描述")
    status = Column(String(32), default="draft", comment="状态: draft/reviewing/published/offline")
    version = Column(Integer, default=1, comment="版本号")
    source_file = Column(String(256), comment="来源文件")
    reviewed_by = Column(String(64), comment="审核人")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 关联
    variants = relationship("KnowledgeQuestionVariant", back_populates="knowledge", cascade="all, delete-orphan")
    keywords = relationship("KnowledgeKeyword", back_populates="knowledge", cascade="all, delete-orphan")
    attachments = relationship("KnowledgeAttachment", back_populates="knowledge", cascade="all, delete-orphan")
    versions = relationship("KnowledgeVersion", back_populates="knowledge", cascade="all, delete-orphan")


class KnowledgeQuestionVariant(Base):
    """问法变体表"""
    __tablename__ = "knowledge_question_variant"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_text = Column(String(512), nullable=False, index=True, comment="用户问法变体")
    source = Column(String(32), default="manual", comment="来源: manual/import/real_conversation")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("KnowledgeAnswer", back_populates="variants")


class KnowledgeKeyword(Base):
    """关键词表"""
    __tablename__ = "knowledge_keyword"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True, comment="关键词")
    keyword_type = Column(String(32), default="normal", comment="类型: normal/synonym/business_term")
    weight = Column(Integer, default=1, comment="权重")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("KnowledgeAnswer", back_populates="keywords")


class KnowledgeAttachment(Base):
    """知识附件表"""
    __tablename__ = "knowledge_attachment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(256), nullable=False, comment="文件名")
    file_type = Column(String(32), comment="文件类型: image/video/document/link")
    file_url = Column(String(512), nullable=False, comment="文件URL")
    file_size = Column(Integer, comment="文件大小(字节)")
    display_order = Column(Integer, default=0, comment="显示顺序")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("KnowledgeAnswer", back_populates="attachments")


class KnowledgeVersion(Base):
    """知识版本历史表"""
    __tablename__ = "knowledge_version"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False, comment="版本号")
    snapshot = Column(JSON, nullable=False, comment="知识快照(完整JSON)")
    change_type = Column(String(32), comment="变更类型: create/update/publish/offline")
    change_note = Column(Text, comment="变更说明")
    changed_by = Column(String(64), comment="变更人")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("KnowledgeAnswer", back_populates="versions")


class FAQCard(Base):
    """高频问题卡片表"""
    __tablename__ = "faq_card"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(64), unique=True, index=True, nullable=False, comment="卡片编码")
    business_area = Column(String(32), nullable=False, default="dashcam", comment="业务领域")
    title = Column(String(256), nullable=False, comment="卡片标题")
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="SET NULL"), comment="关联知识ID")
    category = Column(String(64), comment="分类")
    display_order = Column(Integer, default=0, comment="显示顺序")
    icon_url = Column(String(512), comment="图标URL")
    is_active = Column(Boolean, default=True, comment="是否启用")
    click_count = Column(Integer, default=0, comment="点击量")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QueryIntentConfig(Base):
    """查询意图配置表 (对应Excel 02_查询问题库, 13条)"""
    __tablename__ = "query_intent_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_type_code = Column(String(64), unique=True, index=True, nullable=False, comment="查询类型编码 (QRY001-QRY013)")
    display_name = Column(String(128), nullable=False, comment="查询意图名称")
    business_area = Column(String(32), default="dashcam", comment="业务领域")
    required_slots = Column(JSON, comment="必填槽位配置 [{field, display, type, collect_prompt}]")
    data_source = Column(String(64), comment="数据源: operational_db")
    match_conditions = Column(JSON, comment="匹配条件 [{\"field\":\"vin\",\"op\":\"eq\"}]")
    return_fields = Column(JSON, comment="返回字段 [{\"backend\":\"vin\",\"display\":\"车架号\"}]")
    reply_template_normal = Column(Text, comment="正常结果回复模板 ({{}}占位)")
    reply_template_empty = Column(Text, comment="空结果回复模板")
    escalation_rule = Column(JSON, comment="升级规则 {\"max_retry\":2,\"empty_transfer\":true}")
    auto_reply = Column(Boolean, default=True, comment="是否允许自动回复")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
