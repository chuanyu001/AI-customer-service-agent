# 数据库迁移脚本: 单表 → 四业务分表
# 1. 建新表 (dashcam_* / wifi_* / data_* / refueling_*)
# 2. 迁移 knowledge_answer 144条 → dashcam_knowledge (保留原ID)
# 3. 迁移 variant/keyword/attachment/faq_card → dashcam_*
# 4. 从汇总Excel导入 WiFi/流量/加油 37条到各自表
# 5. 旧表保留作备份 (不删)
#
# 用法: python scripts/migrate_to_multi_table.py

import sys
import os
import asyncio
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
import jieba
from sqlalchemy import select, text
from app.core.database import get_session_factory, get_engine, close_db, Base
from app.models import (
    # 旧表 (读源数据)
    KnowledgeAnswer, KnowledgeQuestionVariant, KnowledgeKeyword,
    KnowledgeAttachment, FAQCard,
    # 新表 (写入)
    DashcamKnowledge, DashcamVariant, DashcamKeyword, DashcamAttachment, DashcamFaqCard,
    WifiKnowledge, WifiVariant, WifiKeyword,
    DataKnowledge, DataVariant, DataKeyword,
    RefuelingKnowledge, RefuelingVariant, RefuelingKeyword,
)

EXCEL_PATH = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版6.22\知识库汇总版6.22.xlsx"

# 三业务 6.24 润色版知识库 (列结构已与记录仪统一, 含「是否对客」「答复策略」)
KB_DIR = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版"
THREE_BIZ_FILES = {
    "wifi": "WiFi套餐知识库润色版6.24.xlsx",
    "data": "基础流量处理知识库润色版6.24.xlsx",
    "refueling": "折扣加油知识库润色版6.24.xlsx",
}


async def create_new_tables():
    """建所有新表"""
    print("🔨 创建新表...")
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, tables=[
            DashcamKnowledge.__table__, DashcamVariant.__table__,
            DashcamKeyword.__table__, DashcamAttachment.__table__, DashcamFaqCard.__table__,
            WifiKnowledge.__table__, WifiVariant.__table__, WifiKeyword.__table__,
            DataKnowledge.__table__, DataVariant.__table__, DataKeyword.__table__,
            RefuelingKnowledge.__table__, RefuelingVariant.__table__, RefuelingKeyword.__table__,
        ])
    print("  ✅ 新表创建完成")


async def migrate_dashcam():
    """迁移行车记录仪数据 (保留原ID)"""
    print("\n📦 迁移行车记录仪数据...")
    async with get_session_factory()() as db:
        # 知识主表
        rows = (await db.execute(select(KnowledgeAnswer))).scalars().all()
        print(f"  读取 {len(rows)} 条知识")
        for r in rows:
            db.add(DashcamKnowledge(
                id=r.id,  # 保留原ID
                knowledge_code=r.knowledge_code,
                category_l1=r.category_l1,
                category_l2=r.category_l2,
                manufacturer=r.manufacturer,
                standard_question=r.standard_question,
                standard_answer=r.standard_answer,
                polished_answer=r.polished_answer,
                answer_type=r.answer_type,
                need_brand=r.need_brand,
                need_attachment=r.need_attachment,
                risk_level=r.risk_level,
                auto_reply=r.auto_reply,
                transfer_condition=r.transfer_condition,
                transfer_prompt=getattr(r, "transfer_prompt", None),
                status=r.status,
                version=r.version,
                source_file=r.source_file,
            ))

        # 问法变体
        variants = (await db.execute(select(KnowledgeQuestionVariant))).scalars().all()
        print(f"  读取 {len(variants)} 条问法变体")
        for v in variants:
            db.add(DashcamVariant(
                id=v.id, knowledge_id=v.knowledge_id,
                variant_text=v.variant_text, source=v.source, is_active=v.is_active,
            ))

        # 关键词
        keywords = (await db.execute(select(KnowledgeKeyword))).scalars().all()
        print(f"  读取 {len(keywords)} 条关键词")
        for k in keywords:
            db.add(DashcamKeyword(
                id=k.id, knowledge_id=k.knowledge_id,
                keyword=k.keyword, keyword_type=k.keyword_type, weight=k.weight,
            ))

        # 附件
        attachments = (await db.execute(select(KnowledgeAttachment))).scalars().all()
        print(f"  读取 {len(attachments)} 条附件")
        for a in attachments:
            db.add(DashcamAttachment(
                id=a.id, knowledge_id=a.knowledge_id,
                file_name=a.file_name, file_type=a.file_type, file_url=a.file_url,
                file_size=a.file_size, display_order=a.display_order,
            ))

        # FAQ卡片
        faqs = (await db.execute(select(FAQCard).where(FAQCard.business_area == "dashcam"))).scalars().all()
        print(f"  读取 {len(faqs)} 条FAQ卡片")
        for f in faqs:
            db.add(DashcamFaqCard(
                id=f.id, card_code=f.card_code, title=f.title,
                knowledge_id=f.knowledge_id, category=f.category,
                display_order=f.display_order, icon_url=f.icon_url,
                is_active=f.is_active, click_count=f.click_count,
            ))

        await db.commit()
    print("  ✅ 行车记录仪迁移完成 (保留原ID)")


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return None if s in ("", "nan", "None", "NaT") else s


def _to_bool(v):
    s = _clean(v)
    return s in ("是", "1", "yes", "true", "True")


async def import_three_businesses():
    """从三业务 6.24 润色版Excel导入 WiFi/流量/加油 (含是否对客/答复策略)"""
    print("\n📦 导入 WiFi/流量/加油 三业务...")

    biz_config = [
        ("wifi", WifiKnowledge, WifiVariant, WifiKeyword),
        ("data", DataKnowledge, DataVariant, DataKeyword),
        ("refueling", RefuelingKnowledge, RefuelingVariant, RefuelingKeyword),
    ]

    async with get_session_factory()() as db:
        for biz, KnModel, VarModel, KwModel in biz_config:
            file_path = os.path.join(KB_DIR, THREE_BIZ_FILES.get(biz, ""))
            if not os.path.exists(file_path):
                print(f"  ⚠️ 未找到 {biz} 知识库文件: {file_path}")
                continue

            sheet = pd.read_excel(file_path, sheet_name="01_知识问答库")
            count = 0
            for _, row in sheet.iterrows():
                code = _clean(row.get("知识编号"))
                if not code:
                    continue
                question = _clean(row.get("标准问题"))
                answer = _clean(row.get("标准答案"))
                if not question or not answer:
                    continue

                # 是否对客 → auto_reply
                customer_flag = _clean(row.get("是否对客")) or "对客"

                kn = KnModel(
                    knowledge_code=code,
                    category=_clean(row.get("知识类型")),
                    standard_question=question,
                    common_phrasings=_clean(row.get("常见问法")),
                    standard_answer=answer,
                    polished_answer=_clean(row.get("润色答案")),
                    reference_url=_clean(row.get("参考链接")) or _clean(row.get("来源备注")),
                    need_brand_route=_to_bool(row.get("是否需要识别品牌")),
                    auto_reply=(customer_flag == "对客"),
                    transfer_prompt=_clean(row.get("答复策略")),
                    status="published",
                )
                db.add(kn)
                await db.flush()

                # 问法变体
                phrases = _clean(row.get("常见问法"))
                if phrases:
                    for v in re.split(r"[;；,，\n]", phrases):
                        v = v.strip()
                        if v:
                            db.add(VarModel(knowledge_id=kn.id, variant_text=v, source="import"))

                # 关键词 (jieba分词)
                seen = set()
                for kw in jieba.cut(question):
                    kw = kw.strip()
                    if len(kw) >= 2 and kw not in seen:
                        seen.add(kw)
                        db.add(KwModel(knowledge_id=kn.id, keyword=kw, weight=2))

                count += 1

            await db.commit()
            print(f"  ✅ {biz}: 导入 {count} 条 ({THREE_BIZ_FILES.get(biz)})")


async def verify():
    """验证迁移结果"""
    print("\n🔍 验证迁移结果...")
    async with get_session_factory()() as db:
        for name, model in [("dashcam", DashcamKnowledge), ("wifi", WifiKnowledge),
                            ("data", DataKnowledge), ("refueling", RefuelingKnowledge)]:
            cnt = (await db.execute(select(model))).scalars().all()
            print(f"  {name}_knowledge: {len(cnt)} 条")

        # 验证dashcam ID保留
        first = (await db.execute(select(DashcamKnowledge).where(DashcamKnowledge.id == 1))).scalar_one_or_none()
        print(f"  dashcam id=1: {first.knowledge_code if first else '未找到'} (应=JL0001)")


async def main():
    print(f"📂 源Excel: {EXCEL_PATH}\n")
    await create_new_tables()
    await migrate_dashcam()
    await import_three_businesses()
    await verify()
    await close_db()
    print("\n✅ 迁移全部完成! 旧表保留作备份")


if __name__ == "__main__":
    asyncio.run(main())
