# 会话/消息 ORM 模型
# 运行数据表组: conversation, message, answer_feedback, handoff_ticket, optimization_sample

from sqlalchemy import (
    Column, String, Text, Integer, Boolean, DateTime, JSON, ForeignKey
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class Conversation(Base):
    """会话记录表"""
    __tablename__ = "conversation"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(128), unique=True, index=True, nullable=False, comment="会话UUID")
    user_id = Column(String(128), index=True, comment="用户ID (openid)")
    user_type = Column(String(32), default="guest", comment="用户类型: guest/registered")
    channel = Column(String(32), default="miniprogram", comment="渠道: miniprogram/web")
    entry_point = Column(String(64), comment="入口: 1_module/2_assistant/3_personal")
    business_area = Column(String(32), default="dashcam", comment="业务领域")
    status = Column(String(32), default="active", comment="状态: active/transferred/resolved/closed")
    ai_resolved = Column(Boolean, default=False, comment="AI是否解决")
    transfer_count = Column(Integer, default=0, comment="累计转人工次数")
    message_count = Column(Integer, default=0, comment="消息总数")
    consecutive_fail = Column(Integer, default=0, comment="连续未解决轮次")
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    ended_at = Column(DateTime(timezone=True), comment="结束时间")
    extra_metadata = Column("metadata", JSON, comment="扩展数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 关联
    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    """消息记录表"""
    __tablename__ = "message"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id = Column(String(128), unique=True, index=True, nullable=False, comment="消息UUID")
    seq = Column(Integer, nullable=False, comment="会话内序号")
    role = Column(String(16), nullable=False, comment="角色: user/assistant/system")
    content = Column(Text, nullable=False, comment="消息内容")
    content_type = Column(String(32), default="text", comment="text/image/voice/video/card")
    media_url = Column(String(512), comment="媒体URL")
    action = Column(String(32), comment="动作: auto_reply/ask_info/query_result/transfer")
    reply_type = Column(String(32), comment="回复类型: knowledge_answer/slot_collection/query_result/handoff/greeting/fallback")
    knowledge_id = Column(Integer, comment="关联知识ID")
    knowledge_code = Column(String(64), comment="关联知识编码")
    query_type_code = Column(String(64), comment="查询类型编码")
    query_data = Column(JSON, comment="查询数据")
    intent_result = Column(JSON, comment="意图识别结果")
    extra_metadata = Column("metadata", JSON, comment="扩展数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")
    feedback = relationship("AnswerFeedback", back_populates="message", uselist=False, cascade="all, delete-orphan")


class AnswerFeedback(Base):
    """回答评价表"""
    __tablename__ = "answer_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False)
    message_id = Column(Integer, ForeignKey("message.id", ondelete="CASCADE"), nullable=False, unique=True)
    rating = Column(Integer, comment="评分: 1-5")
    is_helpful = Column(Boolean, comment="是否有帮助")
    feedback_type = Column(String(32), comment="positive/negative/neutral")
    comment = Column(Text, comment="文字反馈")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    message = relationship("Message", back_populates="feedback")


class HandoffTicket(Base):
    """转人工工单表"""
    __tablename__ = "handoff_ticket"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String(64), unique=True, index=True, nullable=False, comment="工单UUID")
    conversation_id = Column(Integer, ForeignKey("conversation.id", ondelete="CASCADE"), nullable=False, index=True)
    reason_type = Column(String(64), nullable=False, comment="原因类型: consecutive_fail/keyword/user_request/out_of_scope/risk")
    reason_detail = Column(String(256), comment="转人工详细原因")
    summary = Column(Text, comment="AI对话摘要")
    collected_info = Column(JSON, comment="已收集信息 (品牌/VIN/终端号)")
    business_context = Column(Text, comment="业务上下文 (运营数据查询结果)")
    priority = Column(String(16), default="normal", comment="优先级: low/normal/high/urgent")
    status = Column(String(32), default="pending", comment="状态: pending/assigned/processing/resolved/closed")
    qiyu_session_id = Column(String(128), comment="七鱼会话ID")
    assigned_to = Column(String(64), comment="分配客服")
    contact_info = Column(JSON, comment="联系方式 (非工作时间)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class OptimizationSample(Base):
    """优化样本池表"""
    __tablename__ = "optimization_sample"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_type = Column(String(64), nullable=False, index=True, comment="类型: no_match/low_confidence/bad_answer/user_complaint")
    user_query = Column(Text, nullable=False, comment="用户原始问题")
    intent_result = Column(JSON, comment="意图识别结果")
    actual_intent = Column(String(64), comment="人工标注实际意图")
    suggested_knowledge_id = Column(Integer, comment="建议关联知识ID")
    correct_answer = Column(Text, comment="正确答案")
    notes = Column(Text, comment="备注")
    status = Column(String(32), default="pending", index=True, comment="状态: pending/reviewing/annotated/applied")
    conversation_id = Column(Integer, comment="关联会话ID")
    message_id = Column(Integer, comment="关联消息ID")
    reviewed_by = Column(String(64), comment="审核人")
    reviewed_at = Column(DateTime(timezone=True), comment="审核时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
