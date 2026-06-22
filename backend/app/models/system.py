# 系统配置 ORM 模型
# 系统配置表组: system_config, data_dictionary, event_log

from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, Boolean, DateTime, JSON, UniqueConstraint
)
from sqlalchemy.sql import func
from app.core.database import Base


class SystemConfig(Base):
    """系统配置表"""
    __tablename__ = "system_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(64), unique=True, index=True, nullable=False, comment="配置键")
    config_value = Column(Text, comment="配置值")
    config_type = Column(String(32), default="string", comment="类型: string/int/float/bool/json")
    description = Column(String(256), comment="说明")
    is_editable = Column(Boolean, default=True, comment="是否可编辑")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DataDictionary(Base):
    """数据字典表"""
    __tablename__ = "data_dictionary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dict_type = Column(String(64), nullable=False, index=True, comment="字典类型")
    dict_code = Column(String(64), nullable=False, comment="字典编码")
    dict_value = Column(String(256), nullable=False, comment="字典值")
    display_order = Column(Integer, default=0, comment="排序")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("dict_type", "dict_code", name="uq_dict_type_code"),
    )


class EventLog(Base):
    """事件日志表"""
    __tablename__ = "event_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False, index=True, comment="事件类型: workflow_node/llm_call/api_call/error")
    event_name = Column(String(128), nullable=False, comment="事件名称")
    event_data = Column(JSON, comment="事件数据")
    conversation_id = Column(Integer, index=True, comment="关联会话ID")
    user_id = Column(String(128), comment="用户ID")
    duration_ms = Column(Integer, comment="耗时(毫秒)")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
