# 业务数据 ORM 模型
# 业务事实数据表组: brand_info, brand_mapping, field_dictionary, operational_device, device_vehicle_relation

from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, Boolean, DateTime, JSON, ForeignKey, Float
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base


class BrandInfo(Base):
    """品牌信息表 (对应Excel 03_品牌识别规则, 7条)"""
    __tablename__ = "brand_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_code = Column(String(32), unique=True, nullable=False, comment="品牌编码")
    brand_name = Column(String(64), nullable=False, comment="品牌名称 (极目(GPS+BD))")
    short_name = Column(String(32), comment="简称")
    aliases = Column(JSON, comment="别名列表 [\"极目\",\"鱼快\"]")
    business_area = Column(String(32), default="dashcam", index=True, comment="业务领域")
    priority = Column(Integer, default=0, index=True, comment="识别优先级 (1-7)")
    id_format_rules = Column(JSON, comment="ID格式正则规则")
    mcu_verify_rule = Column(String(256), comment="MCU验证规则")
    contact_phone = Column(String(32), comment="厂家电话")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BrandMapping(Base):
    """品牌映射表 (VIN前缀/终端号前缀 → 品牌)"""
    __tablename__ = "brand_mapping"

    id = Column(Integer, primary_key=True, autoincrement=True)
    brand_id = Column(Integer, ForeignKey("brand_info.id", ondelete="CASCADE"), nullable=False, index=True)
    match_type = Column(String(32), nullable=False, comment="匹配类型: vin_prefix/terminal_prefix/device_model")
    match_value = Column(String(128), nullable=False, index=True, comment="匹配值")
    description = Column(String(256), comment="描述")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class FieldDictionary(Base):
    """运营字段字典表 (对应Excel 04_运营字段字典, 22条)"""
    __tablename__ = "field_dictionary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    backend_field = Column(String(128), nullable=False, index=True, comment="后端字段名")
    display_name = Column(String(128), nullable=False, comment="驾驶员友好名称")
    business_area = Column(String(32), default="dashcam", index=True, comment="业务领域")
    field_type = Column(String(32), comment="字段类型: string/int/datetime")
    can_show_customer = Column(Boolean, default=False, comment="是否可展示给客户")
    description = Column(String(256), comment="使用说明")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OperationalDevice(Base):
    """运营平台设备数据表 (360k行)"""
    __tablename__ = "operational_device"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    business_area = Column(String(32), default="dashcam", index=True, comment="业务领域")
    vin = Column(String(32), index=True, comment="车架号")
    plate_number = Column(String(16), index=True, comment="车牌号")
    terminal_id = Column(String(64), index=True, comment="终端号")
    sim_iccid = Column(String(32), index=True, comment="SIM卡ICCID")
    brand_id = Column(Integer, index=True, comment="品牌ID")
    device_model = Column(String(64), comment="设备型号")
    online_status = Column(String(16), comment="在线状态")
    gps_status = Column(String(16), comment="定位状态")
    service_provider = Column(String(64), comment="服务商")
    service_expiry = Column(DateTime(timezone=True), comment="服务到期日")
    firmware_version = Column(String(32), comment="固件版本")
    mcu_version = Column(String(32), comment="MCU版本")
    last_online_time = Column(DateTime(timezone=True), comment="最后在线时间")
    extra_metadata = Column("metadata", JSON, comment="扩展字段")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class DeviceVehicleRelation(Base):
    """设备-车辆-SIM关系表"""
    __tablename__ = "device_vehicle_relation"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    device_id = Column(BigInteger, index=True, comment="设备ID")
    vehicle_id = Column(String(64), index=True, comment="车辆标识")
    sim_iccid = Column(String(32), index=True, comment="SIM卡号")
    relation_type = Column(String(32), default="current", comment="current/history")
    effective_time = Column(DateTime(timezone=True), comment="生效时间")
    expire_time = Column(DateTime(timezone=True), comment="失效时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
