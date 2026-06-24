# 修正知识类型字典: 按业务拆分dict_type, 纳入四业务全部知识类型
# knowledge_type → knowledge_type_dashcam/wifi/data/refueling
# 用法: python scripts/fix_knowledge_type_dict.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select
from app.core.database import get_session_factory
from app.models import DataDictionary

# 四业务的知识类型 (按实际数据归纳)
BUSINESS_TYPES = {
    "knowledge_type_dashcam": [
        ("fault_troubleshooting", "故障排查"),
        ("device_info", "设备信息"),
        ("operation_guide", "操作指引"),
        ("driving_monitor", "驾驶监控"),
        ("general_business", "通用业务"),
    ],
    "knowledge_type_wifi": [
        ("register_requirement", "注册与要求"),
        ("package_price", "套餐与价格"),
        ("purchase_usage", "购买与使用"),
        ("vehicle_adaptation", "车型适配与领取"),
    ],
    "knowledge_type_data": [
        ("type_identification", "类型与识别"),
        ("feedback_process", "反馈流程"),
        ("recharge_operation", "充值操作"),
        ("registration_form", "登记表格"),
    ],
    "knowledge_type_refueling": [
        ("purchase_usage", "购买与使用"),
        ("validity_refund", "有效期与退款"),
        ("invoice_application", "发票申请"),
        ("region_oil_type", "适用区域与油型"),
    ],
}


async def main():
    print("🔧 按业务拆分知识类型字典...\n")
    async with get_session_factory()() as db:
        # 1. 删除旧的统一 knowledge_type
        old = (await db.execute(
            select(DataDictionary).where(DataDictionary.dict_type == "knowledge_type")
        )).scalars().all()
        for o in old:
            await db.delete(o)
        await db.commit()
        print(f"  删除旧 knowledge_type: {len(old)} 条")

        # 2. 插入四业务的类型
        total = 0
        for dict_type, items in BUSINESS_TYPES.items():
            for i, (code, value) in enumerate(items, 1):
                db.add(DataDictionary(
                    dict_type=dict_type, dict_code=code,
                    dict_value=value, display_order=i, is_active=True,
                ))
                total += 1
        await db.commit()
        print(f"  插入四业务知识类型: {total} 条")

    # 验证
    print("\n🔍 验证:")
    async with get_session_factory()() as db:
        for dict_type in BUSINESS_TYPES:
            rows = (await db.execute(
                select(DataDictionary).where(DataDictionary.dict_type == dict_type)
                .order_by(DataDictionary.display_order)
            )).scalars().all()
            biz = dict_type.replace("knowledge_type_", "")
            types = " / ".join(r.dict_value for r in rows)
            print(f"  {biz}({len(rows)}类): {types}")

    print("\n✅ 完成")


if __name__ == "__main__":
    asyncio.run(main())
