# 导入有为设备明细表 (10010台) 到 youwei_device 表
# 用法: python scripts/import_youwei_device.py
# 终端ID号转字符串存储, 避免精度丢失

import sys
import os
import asyncio
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
from sqlalchemy import select, delete
from app.core.database import get_session_factory
from app.models import YouweiDevice

EXCEL_PATH = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版\有为设备明细10010台.xlsx"


def _clean_str(v):
    """转字符串, 去小数点(Excel数字读成float), 去空"""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float):
        # 790010437330.0 → "790010437330"
        return str(int(v)) if v == int(v) else str(v)
    s = str(v).strip()
    return None if s in ("", "nan", "None") else s


def _parse_date(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return pd.to_datetime(v).to_pydatetime()
    except Exception:
        return None


async def main():
    print(f"📂 读取: {EXCEL_PATH}")
    df = pd.read_excel(EXCEL_PATH, sheet_name=0)
    print(f"   {len(df)} 行, 列: {list(df.columns)}\n")

    async with get_session_factory()() as db:
        # 清空旧数据
        await db.execute(delete(YouweiDevice))
        await db.commit()
        print("🗑️ 清空旧数据")

        count = 0
        skip = 0
        for _, row in df.iterrows():
            terminal_id = _clean_str(row.get("终端ID号"))
            if not terminal_id:
                skip += 1
                continue
            db.add(YouweiDevice(
                terminal_id=terminal_id,
                sim_no_11=_clean_str(row.get("SIM卡号(11位)")),
                iccid=_clean_str(row.get("ICCID号")),
                imei=_clean_str(row.get("IMEI")),
                product_model=_clean_str(row.get("产品型号")),
                produce_date=_parse_date(row.get("生产日期")),
                imsi=_clean_str(row.get("IMSI")),
            ))
            count += 1
            if count % 2000 == 0:
                await db.commit()
                print(f"  已导入 {count}...")

        await db.commit()

    print(f"\n✅ 导入完成: {count} 条, 跳过(无终端ID): {skip} 条")

    # 验证
    async with get_session_factory()() as db:
        total = (await db.execute(select(YouweiDevice))).scalars().all()
        print(f"   youwei_device 表现有: {len(total)} 条")
        if total:
            sample = total[0]
            print(f"   样例: terminal_id={sample.terminal_id} iccid={sample.iccid} model={sample.product_model}")


if __name__ == "__main__":
    asyncio.run(main())
