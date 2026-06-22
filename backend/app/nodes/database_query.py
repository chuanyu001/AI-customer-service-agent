# 节点5: 数据库查询
# 运营平台精确查询 → 字段映射 → 结果格式化

from typing import List, Dict, Any, Optional
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from ..graph.state import WorkflowState
from ..models import OperationalDevice, FieldDictionary, QueryIntentConfig


async def database_query_node(state: WorkflowState) -> WorkflowState:
    """数据库查询节点

    处理流程:
    1. 获取查询类型编码和已收集槽位
    2. 构建SQL查询条件
    3. 查询 operational_device 表
    4. 字段名映射 (后端 → 用户友好名)
    5. 过滤内部字段 (can_show_customer=0)
    6. 记录查询日志
    """
    query_type_code = state.get("query_type_code", "")
    collected_slots = state.get("collected_slots", {})

    state["query_result"] = None
    state["query_result_count"] = 0
    state["query_success"] = False
    state["query_error"] = None

    if not query_type_code or not collected_slots:
        return state

    # 实际查询由 query_with_db 执行
    return state


async def database_query_with_db(state: WorkflowState, db: AsyncSession) -> WorkflowState:
    """带数据库会话的查询 (实际调用入口)"""
    query_type_code = state.get("query_type_code", "")
    collected_slots = state.get("collected_slots", {})

    state["query_result"] = None
    state["query_result_count"] = 0
    state["query_success"] = False
    state["query_error"] = None

    if not query_type_code:
        return state

    try:
        # ============================================
        # Step 1: 构建查询条件
        # ============================================
        conditions = []

        # VIN
        vin = collected_slots.get("vin", "")
        if vin:
            conditions.append(OperationalDevice.vin == vin)

        # 终端号
        terminal_id = collected_slots.get("terminal_id", "")
        if terminal_id:
            conditions.append(OperationalDevice.terminal_id == terminal_id)

        # SIM卡号
        sim_iccid = collected_slots.get("sim_iccid", "")
        if sim_iccid:
            conditions.append(OperationalDevice.sim_iccid == sim_iccid)

        # 车牌号
        plate_number = collected_slots.get("plate_number", "")
        if plate_number:
            conditions.append(OperationalDevice.plate_number == plate_number)

        if not conditions:
            state["query_error"] = "缺少查询条件"
            return state

        # ============================================
        # Step 2: 执行查询
        # ============================================
        stmt = select(OperationalDevice).where(or_(*conditions)).limit(10)
        result = await db.execute(stmt)
        devices = result.scalars().all()

        if not devices:
            state["query_result_count"] = 0
            state["query_success"] = True
            return state

        # ============================================
        # Step 3: 字段映射 + 过滤
        # ============================================
        # 获取字段字典
        field_stmt = select(FieldDictionary).where(
            FieldDictionary.business_area == state.get("business_area", "dashcam")
        )
        field_result = await db.execute(field_stmt)
        field_dicts = {f.backend_field: f for f in field_result.scalars().all()}

        # 获取查询配置的返回字段
        config_stmt = select(QueryIntentConfig).where(
            QueryIntentConfig.query_type_code == query_type_code
        )
        config_result = await db.execute(config_stmt)
        config = config_result.scalar_one_or_none()

        allowed_fields = None
        if config and config.return_fields:
            allowed_fields = {rf.get("backend", "") for rf in config.return_fields}

        # 格式化结果
        formatted_results = []
        for device in devices:
            item = {}
            for col in OperationalDevice.__table__.columns:
                field_name = col.name
                value = getattr(device, field_name, None)

                # 过滤内部字段
                if field_name in ("id", "metadata", "created_at", "updated_at"):
                    continue

                # 检查是否可对客展示
                field_dict = field_dicts.get(field_name)
                if field_dict and not field_dict.can_show_customer:
                    continue

                # 字段名映射
                display_name = field_dict.display_name if field_dict else field_name

                # 允许字段过滤
                if allowed_fields and field_name not in allowed_fields:
                    continue

                if value is not None:
                    item[display_name] = str(value)

            if item:
                formatted_results.append(item)

        state["query_result"] = formatted_results
        state["query_result_count"] = len(formatted_results)
        state["query_success"] = True

        # 将查询结果中的重要信息存入 collected_slots
        if devices:
            device = devices[0]
            if device.vin:
                state["collected_slots"]["vin"] = device.vin
            if device.terminal_id:
                state["collected_slots"]["terminal_id"] = device.terminal_id
            if device.sim_iccid:
                state["collected_slots"]["sim_iccid"] = device.sim_iccid
            if device.brand_id:
                state["collected_slots"]["brand_id"] = device.brand_id

    except Exception as e:
        state["query_success"] = False
        state["query_error"] = str(e)

    return state


def format_query_result(
    results: List[Dict],
    template_normal: str = "",
    template_empty: str = "",
) -> str:
    """格式化查询结果为可读文本"""
    if not results:
        return template_empty or "未查询到相关设备信息。请确认您提供的信息是否正确, 或联系人工客服。"

    if template_normal:
        # Jinja2模板替换
        import re
        response = template_normal
        data = results[0]  # 使用第一条结果
        for key, value in data.items():
            response = response.replace(f"{{{{{key}}}}}", str(value))
        return response

    # 默认格式化
    lines = ["查询到以下设备信息:"]
    for i, item in enumerate(results, 1):
        lines.append(f"\n📱 设备 {i}:")
        for key, value in item.items():
            lines.append(f"  • {key}: {value}")

    return "\n".join(lines)
