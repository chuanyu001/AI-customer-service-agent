# -*- coding: utf-8 -*-
"""将四个 6.24 润色版知识库 Excel 更新到对应数据库分表。
1. 给 dashcam/wifi/data/refueling 四张 knowledge 表补 auto_reply/transfer_prompt 列(缺则加)
2. 按知识编号(knowledge_code) upsert: 更新 standard_question/answer/polished_answer/是否对客/答复策略 等

用法: cd backend && MYSQL_PASSWORD=4531 python ../scripts/update_kb_customer_flag.py
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
from sqlalchemy import text
from app.core.database import get_session_factory, get_engine, close_db

KB_DIR = r"D:/wuchu/Desktop/personalfiles/实习/kefu-agent/agent知识库汇总版"
FILES = {
    "dashcam": "记录仪知识库润色版6.24.xlsx",
    "wifi": "WiFi套餐知识库润色版6.24.xlsx",
    "data": "基础流量处理知识库润色版6.24.xlsx",
    "refueling": "折扣加油知识库润色版6.24.xlsx",
}
TABLES = {
    "dashcam": "dashcam_knowledge",
    "wifi": "wifi_knowledge",
    "data": "data_knowledge",
    "refueling": "refueling_knowledge",
}


def clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None", "NaT") else s


async def ensure_columns(engine):
    """给四张表补 auto_reply / transfer_prompt 列(缺则加)"""
    print("🔧 检查/补全 auto_reply、transfer_prompt 列...")
    add_sqls = {
        "dashcam": [  # 已有auto_reply, 只缺transfer_prompt
            ("transfer_prompt", "ADD COLUMN transfer_prompt TEXT COMMENT '转人工前追问语'"),
        ],
        "wifi": [
            ("auto_reply", "ADD COLUMN auto_reply BOOLEAN DEFAULT TRUE COMMENT '是否对客自动回复'"),
            ("transfer_prompt", "ADD COLUMN transfer_prompt TEXT COMMENT '转人工前追问语'"),
        ],
        "data": [
            ("auto_reply", "ADD COLUMN auto_reply BOOLEAN DEFAULT TRUE COMMENT '是否对客自动回复'"),
            ("transfer_prompt", "ADD COLUMN transfer_prompt TEXT COMMENT '转人工前追问语'"),
        ],
        "refueling": [
            ("auto_reply", "ADD COLUMN auto_reply BOOLEAN DEFAULT TRUE COMMENT '是否对客自动回复'"),
            ("transfer_prompt", "ADD COLUMN transfer_prompt TEXT COMMENT '转人工前追问语'"),
        ],
    }
    async with engine.begin() as conn:
        for biz, cols in add_sqls.items():
            t = TABLES[biz]
            for col_name, col_def in cols:
                # 检查列是否存在
                exists = await conn.execute(text(f"SHOW COLUMNS FROM {t} LIKE '{col_name}'"))
                if exists.fetchone() is None:
                    await conn.execute(text(f"ALTER TABLE {t} {col_def}"))
                    print(f"  ✅ {t}: 新增列 {col_name}")
                else:
                    print(f"  - {t}: 列 {col_name} 已存在, 跳过")


async def upsert_business(db, biz):
    """三业务(wifi/data/refueling): 按knowledge_code更新"""
    t = TABLES[biz]
    df = pd.read_excel(os.path.join(KB_DIR, FILES[biz]), sheet_name="01_知识问答库")

    upd = text(f"""
        UPDATE {t} SET
            standard_question=:q, standard_answer=:a, polished_answer=:pa,
            common_phrasings=:cp, category=:cat,
            auto_reply=:ar, transfer_prompt=:tp, status='published'
        WHERE knowledge_code=:code
    """)
    ins = text(f"""
        INSERT INTO {t}
            (knowledge_code, category, standard_question, common_phrasings,
             standard_answer, polished_answer, auto_reply, transfer_prompt, status)
        VALUES (:code, :cat, :q, :cp, :a, :pa, :ar, :tp, 'published')
    """)
    updated, inserted = 0, 0
    for _, row in df.iterrows():
        code = clean(row.get("知识编号"))
        if not code:
            continue
        params = dict(
            code=code, q=clean(row.get("标准问题")) or "",
            a=clean(row.get("标准答案")) or "",
            pa=clean(row.get("润色答案")),
            cp=clean(row.get("常见问法")),
            cat=clean(row.get("知识类型")),
            ar=(clean(row.get("是否对客")) or "对客") == "对客",
            tp=clean(row.get("答复策略")),
        )
        r = await db.execute(upd, params)
        if r.rowcount == 0:
            await db.execute(ins, params)
            inserted += 1
        else:
            updated += 1
    await db.commit()
    return updated, inserted, len(df)


async def upsert_dashcam(db):
    """记录仪: 字段名不同(category_l1/l2, manufacturer, need_brand, need_attachment, source_file)"""
    t = TABLES["dashcam"]
    df = pd.read_excel(os.path.join(KB_DIR, FILES["dashcam"]), sheet_name="01_知识问答库")

    upd = text(f"""
        UPDATE {t} SET
            standard_question=:q, standard_answer=:a, polished_answer=:pa,
            category_l1=:c1, category_l2=:c2, manufacturer=:mfr,
            need_brand=:nb, need_attachment=:na,
            auto_reply=:ar, transfer_prompt=:tp, source_file=:sf, status='published'
        WHERE knowledge_code=:code
    """)
    updated, missed = 0, []
    for _, row in df.iterrows():
        code = clean(row.get("知识编号"))
        if not code:
            continue
        params = dict(
            code=code, q=clean(row.get("标准问题")) or "",
            a=clean(row.get("标准答案")) or "",
            pa=clean(row.get("润色答案")),
            c1=clean(row.get("产品模块")), c2=clean(row.get("知识类型")),
            mfr=clean(row.get("厂家")),
            nb=(clean(row.get("是否需要识别品牌")) in ("是", "1", "yes", "true")),
            na=(clean(row.get("是否需要附件")) in ("是", "1", "yes", "true")),
            ar=(clean(row.get("是否对客")) or "对客") == "对客",
            tp=clean(row.get("答复策略")),
            sf=clean(row.get("答复策略")),
        )
        r = await db.execute(upd, params)
        if r.rowcount == 0:
            missed.append(code)
        else:
            updated += 1
    await db.commit()
    return updated, missed, len(df)


async def main():
    engine = get_engine()
    await ensure_columns(engine)

    async with get_session_factory()() as db:
        # 记录仪
        upd, missed, total = await upsert_dashcam(db)
        print(f"\n✅ dashcam: 更新 {upd}/{total} 条" + (f", 未匹配编号: {missed}" if missed else ""))

    async with get_session_factory()() as db:
        for biz in ["wifi", "data", "refueling"]:
            upd, ins, total = await upsert_business(db, biz)
            print(f"✅ {biz}: 更新 {upd} 条, 新增 {ins} 条 (Excel {total} 条)")

    # 抽查转人工标记
    print("\n🔍 抽查 auto_reply=0 (转人工) 条目:")
    async with engine.connect() as conn:
        for biz in ["wifi", "data", "refueling"]:
            t = TABLES[biz]
            r = await conn.execute(text(
                f"SELECT knowledge_code, auto_reply, LEFT(transfer_prompt,30) FROM {t} WHERE auto_reply=0"
            ))
            rows = r.fetchall()
            print(f"  {t}: {len(rows)} 条转人工 -> {[r[0] for r in rows]}")

    await close_db()
    print("\n✅ 全部更新完成")


if __name__ == "__main__":
    asyncio.run(main())
