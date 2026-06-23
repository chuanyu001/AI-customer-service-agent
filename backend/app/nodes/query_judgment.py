# 节点4: 查询类型判断 + 条件收集
# 匹配13种查询意图 → 检查槽位 → 渐进式追问

import re
from typing import List, Optional
from ..graph.state import WorkflowState, SlotItem
from ..services.llm_service import get_llm


async def query_judgment_node(state: WorkflowState) -> WorkflowState:
    """查询类型判断 + 条件收集节点

    处理流程:
    1. 判断用户意图是否对应13种查询类型
    2. 从 query_intent_config 表加载配置
    3. 检查 required_slots 是否满足
    4. 不满足 → 生成渐进式追问
    5. 满足 → 标记 slots_collected=True
    """
    query = state.get("rewritten_query", state.get("query", ""))
    collected_slots = state.get("collected_slots", {})

    state["is_live_query"] = False
    state["query_type_code"] = None
    state["slots_collected"] = False
    state["required_slots"] = []

    # 如果意图不是 live_query, 且知识检索有结果, 直接跳过
    intent_type = state.get("intent_type", "unknown")
    matched_ids = state.get("matched_knowledge_ids", [])
    if intent_type != "live_query" and matched_ids:
        return state

    state["is_live_query"] = True

    # ============================================
    # Step 1: 尝试匹配查询类型
    # ============================================
    # 从查询意图关键词推断
    query_type_code = _match_query_type(query)

    if not query_type_code:
        # 无法匹配查询类型 → 不视为查询意图
        state["is_live_query"] = False
        return state

    state["query_type_code"] = query_type_code

    # ============================================
    # Step 2: 检查槽位 (必填信息)
    # ============================================
    required_slots = _get_required_slots(query_type_code)
    state["required_slots"] = required_slots

    missing_slots = []
    for slot in required_slots:
        field = slot.get("field", "")
        if field not in collected_slots or not collected_slots[field]:
            missing_slots.append(slot)
        else:
            slot["value"] = collected_slots[field]
            slot["collected"] = True

    # ============================================
    # Step 3: 槽位收集
    # ============================================
    if not missing_slots:
        # 所有槽位已收集
        state["slots_collected"] = True
        state["required_slots"] = required_slots  # 已填充值的槽位
    else:
        # 有缺失槽位 → 生成追问
        state["slots_collected"] = False
        state["pending_slots"] = missing_slots

        # 渐进式追问: 一次只问一个槽位
        first_missing = missing_slots[0]
        retry = first_missing.get("retry_count", 0)

        if retry >= 2:
            # 超过最大重试 → 转人工
            state["should_transfer"] = True
            state["transfer_reason_type"] = "consecutive_fail"
            state["transfer_reason"] = f"无法收集必要信息: {first_missing.get('display', '')}"
        else:
            first_missing["retry_count"] = retry + 1
            state["ask_slot_prompt"] = _generate_slot_prompt(first_missing, collected_slots)

    return state


async def query_judgment_with_db(state: WorkflowState, db) -> WorkflowState:
    """带数据库会话的查询判断 (实际调用入口)"""
    query = state.get("rewritten_query", state.get("query", ""))
    collected_slots = state.get("collected_slots", {})

    state["is_live_query"] = False
    state["query_type_code"] = None
    state["slots_collected"] = False
    state["required_slots"] = []

    intent_type = state.get("intent_type", "unknown")
    matched_ids = state.get("matched_knowledge_ids", [])
    if intent_type != "live_query" and matched_ids:
        return state

    state["is_live_query"] = True

    # 从数据库加载查询意图配置
    from app.models import QueryIntentConfig
    from sqlalchemy import select

    query_type_code = _match_query_type(query)
    if not query_type_code:
        state["is_live_query"] = False
        return state

    state["query_type_code"] = query_type_code

    # 获取配置
    stmt = select(QueryIntentConfig).where(
        QueryIntentConfig.query_type_code == query_type_code,
        QueryIntentConfig.is_active == True,
    )
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()

    if not config:
        state["is_live_query"] = False
        return state

    # 解析槽位
    required_slots = []
    if config.required_slots:
        for slot_cfg in config.required_slots:
            required_slots.append(SlotItem(
                field=slot_cfg.get("field", ""),
                display=slot_cfg.get("display", ""),
                type=slot_cfg.get("type", "string"),
                value=collected_slots.get(slot_cfg.get("field", "")),
                collected=slot_cfg.get("field", "") in collected_slots,
                collect_prompt=slot_cfg.get("collect_prompt", ""),
                retry_count=0,
            ))

    state["required_slots"] = required_slots

    # 检查缺失槽位
    missing_slots = [s for s in required_slots if not s.get("collected")]

    if not missing_slots:
        state["slots_collected"] = True
    else:
        state["slots_collected"] = False
        first_missing = missing_slots[0]
        if first_missing.get("retry_count", 0) >= 2:
            state["should_transfer"] = True
            state["transfer_reason_type"] = "consecutive_fail"
            state["transfer_reason"] = f"无法收集必要信息: {first_missing.get('display', '')}"
        else:
            first_missing["retry_count"] = first_missing.get("retry_count", 0) + 1
            state["ask_slot_prompt"] = _generate_slot_prompt(first_missing, collected_slots)

    return state


# ============================================
# 辅助函数
# ============================================

def _match_query_type(query: str) -> Optional[str]:
    """从查询文本匹配查询类型编码"""
    query_lower = query.lower()

    # 查询意图关键词映射 (来自Excel 02_查询问题库)
    intent_patterns = [
        (r"(sim|卡号|iccid)", "QRY001"),       # query_sim_no
        (r"(终端号|设备id|device.?id)", "QRY002"),  # query_device_id
        (r"(sim.*终端|终端.*sim|卡号.*终端|id.*sim)", "QRY003"),  # query_sim_and_id
        (r"(服务商|运营商)", "QRY004"),          # query_service_provider
        (r"(司机卡|驾驶员卡|ic卡)", "QRY005"),   # query_driver_card_provider
        (r"(车辆信息|车主)", "QRY006"),          # query_vehicle_info_provider
        (r"(续费|续约|到期)", "QRY007"),         # query_renewal_provider
        (r"(服务到期|到期时间)", "QRY008"),       # query_service_expiry
        (r"(缴费|激活|开通)", "QRY009"),          # query_payment_activation
        (r"(在线|离线|状态)", "QRY010"),          # query_online_status
        (r"(品牌|厂家|厂商)", "QRY011"),          # query_device_brand
        (r"(型号|类型|设备类型)", "QRY012"),      # query_device_type
        (r"(流量|套餐|流量卡)", "QRY013"),        # query_traffic_package
    ]

    for pattern, code in intent_patterns:
        if re.search(pattern, query_lower):
            return code

    return None


def _get_required_slots(query_type_code: str) -> List[SlotItem]:
    """获取查询类型所需的槽位 (硬编码兜底, 数据库优先)

    注: 运营平台接口 batchVehicleInfo 仅支持 VIN 查询, 故所有查询类型统一只收集 VIN
    """
    return [SlotItem(
        field="vin",
        display="车架号(VIN)",
        type="string",
        collect_prompt="请提供您的车架号(VIN)",
    )]


def _generate_slot_prompt(slot: SlotItem, collected_slots: dict) -> str:
    """生成槽位询问提示语"""
    return slot.get("collect_prompt", f"请提供您的{slot.get('display', '相关信息')}")
