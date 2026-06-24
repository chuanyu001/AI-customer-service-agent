# 导入运营平台数据 (25.6万行) 到 operational_data 表
# 离线验证用, 接口就绪后可移除
# 用法: python scripts/import_operational_data.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
from sqlalchemy import delete
from app.core.database import get_session_factory, get_engine, Base
from app.models import OperationalData

EXCEL_PATH = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版\运营平台数据.xlsx"


def _clean_str(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float):
        return str(int(v)) if v == int(v) else str(v)
    s = str(v).strip()
    return None if s in ("", "nan", "None", "NaT") else s


def _parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).to_pydatetime()
    except Exception:
        return None


async def main():
    print(f"📂 读取: {EXCEL_PATH}")
    xl = pd.ExcelFile(EXCEL_PATH)
    print(f"   sheets: {xl.sheet_names}\n")

    # 建表
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[OperationalData.__table__])
    print("✅ operational_data 表已创建/确认\n")

    async with get_session_factory()() as db:
        await db.execute(delete(OperationalData))
        await db.commit()
        print("🗑️ 清空旧数据\n")

        total = 0
        seen_vins = set()  # 跨sheet去重
        for sheet_name in xl.sheet_names:
            df = pd.read_excel(EXCEL_PATH, sheet_name=sheet_name)
            print(f"📦 {sheet_name}: {len(df)} 行")

            batch = []
            for _, row in df.iterrows():
                vin = _clean_str(row.get("VIN号"))
                if not vin or vin in seen_vins:
                    continue
                seen_vins.add(vin)
                batch.append(OperationalData(
                    vin=vin,
                    plate_number=_clean_str(row.get("车牌号")),
                    recorder_id=_clean_str(row.get("行车记录仪ID")),
                    terminal_id=_clean_str(row.get("设备终端号")),
                    device_brand=_clean_str(row.get("行车记录仪品牌")),
                    aak_status=_clean_str(row.get("aak状态")),
                    aak_time=_parse_date(row.get("aak时间")),
                    service_provider=_clean_str(row.get("所属服务商")),
                    organization=_clean_str(row.get("所属机构")),
                    register_time=_parse_date(row.get("落籍时间")),
                    net_in_time=_parse_date(row.get("入网时间")),
                    package_name=_clean_str(row.get("套餐名称")),
                    traffic_expire=_parse_date(row.get("流量到期时间")),
                    freight_validity=_clean_str(row.get("货运平台有效期")),
                    order_status=_clean_str(row.get("订单状态")),
                    activate_status=_clean_str(row.get("终端开通状态")),
                    online_status=_clean_str(row.get("终端在线状态")),
                    business_type=_clean_str(row.get("业务类型")),
                ))
                if len(batch) >= 1000:
                    db.add_all(batch)
                    await db.commit()
                    batch = []
                    total += 1000
                    print(f"   已导入 {total}...")

            if batch:
                db.add_all(batch)
                await db.commit()
                total += len(batch)
            print(f"   ✅ {sheet_name} 完成, 累计 {total}")

    print(f"\n✅ 导入完成: 共 {total} 条")

    # 验证
    from sqlalchemy import select, func
    async with get_session_factory()() as db:
        cnt = (await db.execute(select(func.count(OperationalData.id)))).scalar()
        print(f"   operational_data 表: {cnt} 条")
        # 品牌分布
        rows = (await db.execute(
            select(OperationalData.device_brand, func.count(OperationalData.id))
            .group_by(OperationalData.device_brand)
        )).all()
        print("   品牌分布:", {r[0]: r[1] for r in rows})


if __name__ == "__main__":
    asyncio.run(main())
