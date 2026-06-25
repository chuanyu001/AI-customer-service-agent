# 业务数据 ORM 模型
# 业务事实数据表组: brand_info, brand_mapping, field_dictionary, device_vehicle_relation, youwei_device, operational_data

from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, Boolean, DateTime, JSON, ForeignKey
)
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


class YouweiDevice(Base):
    """有为设备明细表 (10010台, 用于区分极目/有为品牌)

    品牌识别逻辑: 运营平台接口返回"鱼快"时, 拿终端ID号查此表
    - 查到 → 有为
    - 查不到 → 极目
    关联键: terminal_id (终端ID号), 对应接口的 recorderId
    """
    __tablename__ = "youwei_device"

    id = Column(Integer, primary_key=True, autoincrement=True)
    terminal_id = Column(String(32), unique=True, index=True, nullable=False, comment="终端ID号 (关联键)")
    sim_no_11 = Column(String(32), comment="SIM卡号(11位)")
    iccid = Column(String(32), index=True, comment="ICCID号")
    imei = Column(String(32), comment="IMEI")
    product_model = Column(String(64), comment="产品型号")
    produce_date = Column(DateTime(timezone=True), comment="生产日期")
    imsi = Column(String(32), comment="IMSI")
    raw_data = Column("metadata", JSON, comment="原始明细全字段(扩展用)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class OperationalData(Base):
    """运营平台数据表 (离线验证用, 接口就绪后可移除/改回接口查询)

    主键: VIN号。用于验证 VIN→品牌/终端号/在线状态 等查询。
    字段对齐运营平台数据Excel的18列。
    """
    __tablename__ = "operational_data"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vin = Column(String(32), index=True, nullable=False, comment="VIN号 (查询主键, 多sheet可能有重复)")
    plate_number = Column(String(16), index=True, comment="车牌号")
    recorder_id = Column(String(32), index=True, comment="行车记录仪ID")
    terminal_id = Column(String(32), index=True, comment="设备终端号")
    device_brand = Column(String(32), index=True, comment="行车记录仪品牌 (鱼快/航天/启明/锐明)")
    aak_status = Column(String(16), comment="aak状态")
    aak_time = Column(DateTime(timezone=True), comment="aak时间")
    service_provider = Column(String(128), comment="所属服务商")
    organization = Column(String(256), comment="所属机构")
    register_time = Column(DateTime(timezone=True), comment="落籍时间")
    net_in_time = Column(DateTime(timezone=True), comment="入网时间")
    package_name = Column(String(128), comment="套餐名称")
    traffic_expire = Column(DateTime(timezone=True), comment="流量到期时间")
    freight_validity = Column(String(128), comment="货运平台有效期")
    order_status = Column(String(32), comment="订单状态")
    activate_status = Column(String(32), comment="终端开通状态")
    online_status = Column(String(32), index=True, comment="终端在线状态")
    business_type = Column(String(32), comment="业务类型")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
