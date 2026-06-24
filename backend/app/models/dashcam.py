# 行车记录仪知识库 ORM 模型 (从 knowledge_answer 拆分)
# 表名前缀 dashcam_, 保留完整字段(品牌/附件/润色/查询关联)
# business_area 字段移除 (表名已区分业务)

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class DashcamKnowledge(Base):
    """行车记录仪知识问答主表 (144条, 含品牌/附件/润色)"""
    __tablename__ = "dashcam_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_code = Column(String(64), unique=True, index=True, nullable=False, comment="知识编码 JL0001~")
    category_l1 = Column(String(64), comment="一级分类")
    category_l2 = Column(String(64), comment="二级分类 (4G离线/查询SIM/按键重启...)")
    manufacturer = Column(String(128), comment="适用厂商 (通用/极目/航天/雅迅/启明/有为)")
    standard_question = Column(String(512), nullable=False, comment="标准问题")
    standard_answer = Column(Text, nullable=False, comment="标准回答")
    polished_answer = Column(Text, comment="大模型润色后的回复(预计算)")
    answer_type = Column(String(32), default="text", comment="回答类型: text/video/image/mixed")
    need_brand = Column(Boolean, default=False, comment="是否需要品牌识别")
    need_attachment = Column(Boolean, default=False, comment="是否需要附件")
    risk_level = Column(String(16), default="low", comment="风险等级: low/medium/high")
    auto_reply = Column(Boolean, default=True, comment="是否对客自动回复(对客=True/转人工=False)")
    transfer_prompt = Column(Text, comment="转人工前追问语(对客类为空)")
    transfer_condition = Column(Text, comment="转人工条件描述")
    status = Column(String(32), default="published", comment="状态: draft/reviewing/published/offline")
    version = Column(Integer, default=1, comment="版本号")
    source_file = Column(String(256), comment="答复策略/来源")
    reviewed_by = Column(String(64), comment="审核人")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    variants = relationship("DashcamVariant", back_populates="knowledge", cascade="all, delete-orphan")
    keywords = relationship("DashcamKeyword", back_populates="knowledge", cascade="all, delete-orphan")
    attachments = relationship("DashcamAttachment", back_populates="knowledge", cascade="all, delete-orphan")


class DashcamVariant(Base):
    """问法变体表"""
    __tablename__ = "dashcam_variant"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("dashcam_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    variant_text = Column(String(512), nullable=False, index=True, comment="用户问法变体")
    source = Column(String(32), default="manual", comment="来源: manual/import/real_conversation")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("DashcamKnowledge", back_populates="variants")


class DashcamKeyword(Base):
    """关键词表"""
    __tablename__ = "dashcam_keyword"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("dashcam_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    keyword = Column(String(128), nullable=False, index=True, comment="关键词")
    keyword_type = Column(String(32), default="normal", comment="类型: normal/synonym/business_term")
    weight = Column(Integer, default=1, comment="权重")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("DashcamKnowledge", back_populates="keywords")


class DashcamAttachment(Base):
    """知识附件表 (视频等)"""
    __tablename__ = "dashcam_attachment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("dashcam_knowledge.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name = Column(String(256), nullable=False, comment="文件名")
    file_type = Column(String(32), comment="文件类型: image/video/document/link")
    file_url = Column(String(512), nullable=False, comment="文件URL")
    file_size = Column(Integer, comment="文件大小(字节)")
    display_order = Column(Integer, default=0, comment="显示顺序")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    knowledge = relationship("DashcamKnowledge", back_populates="attachments")


class DashcamFaqCard(Base):
    """行车记录仪高频问题卡片表"""
    __tablename__ = "dashcam_faq_card"

    id = Column(Integer, primary_key=True, autoincrement=True)
    card_code = Column(String(64), unique=True, index=True, nullable=False, comment="卡片编码")
    title = Column(String(256), nullable=False, comment="卡片标题")
    knowledge_id = Column(Integer, ForeignKey("dashcam_knowledge.id", ondelete="SET NULL"), comment="关联知识ID")
    category = Column(String(64), comment="分类")
    display_order = Column(Integer, default=0, comment="显示顺序")
    icon_url = Column(String(512), comment="图标URL")
    is_active = Column(Boolean, default=True, comment="是否启用")
    click_count = Column(Integer, default=0, comment="点击量")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
