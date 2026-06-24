# 多业务知识库 + 有为设备明细 导入脚本
# 用法: python scripts/import_multi_business.py
#
# 数据源:
#   WiFi套餐知识库确认版6.24.xlsx  → wifi_knowledge 表族 (9条)
#   基础流量处理知识库确认版6.24.xlsx → data_knowledge 表族 (11条)
#   折扣加油知识库确认版6.24.xlsx    → refueling_knowledge 表族 (8条)
#   有为设备10010台明细.xlsx         → youwei_device 表 (10010条)
#
# 策略: 全量替换 — 先删除业务下所有旧数据, 再插入Excel内容
#       变体/关键词/FAQ卡片 同样先删后插

import sys
import os
import asyncio
import re
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
import jieba
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, func
from app.core.database import get_session_factory
from app.models import (
    WifiKnowledge, WifiVariant, WifiKeyword, WifiFaqCard,
    DataKnowledge, DataVariant, DataKeyword, DataFaqCard,
    RefuelingKnowledge, RefuelingVariant, RefuelingKeyword, RefuelingFaqCard,
    YouweiDevice,
)

# ============================================
# 文件路径配置
# ============================================
KB_DIR = r"D:\wuchu\Desktop\personalfiles\实习\kefu-agent\agent知识库汇总版"

BIZ_CONFIG = {
    "wifi": {
        "file": os.path.join(KB_DIR, "WiFi套餐知识库确认版6.24.xlsx"),
        "sheet": 0,
        "model": WifiKnowledge,
        "variant_model": WifiVariant,
        "keyword_model": WifiKeyword,
        "faq_model": WifiFaqCard,
        "table_label": "WiFi套餐",
    },
    "data": {
        "file": os.path.join(KB_DIR, "基础流量处理知识库确认版6.24.xlsx"),
        "sheet": 0,
        "model": DataKnowledge,
        "variant_model": DataVariant,
        "keyword_model": DataKeyword,
        "faq_model": DataFaqCard,
        "table_label": "基础流量处理",
    },
    "refueling": {
        "file": os.path.join(KB_DIR, "折扣加油知识库确认版6.24.xlsx"),
        "sheet": 0,
        "model": RefuelingKnowledge,
        "variant_model": RefuelingVariant,
        "keyword_model": RefuelingKeyword,
        "faq_model": RefuelingFaqCard,
        "table_label": "折扣加油",
    },
}

YOUWEI_FILE = os.path.join(KB_DIR, "有为设备10010台明细.xlsx")
YOUWEI_SHEET = "有为设备明细--共计10010台"


class MultiBusinessImporter:
    """多业务知识库 + 有为设备 导入器"""

    def __init__(self):
        self.stats = {}

    # ============================================
    # 知识库导入 (WiFi / Data / Refueling)
    # ============================================
    async def import_kb(self, db: AsyncSession, biz_key: str):
        """导入单个业务的知识库 (全量替换: 先删后插)"""
        cfg = BIZ_CONFIG[biz_key]
        filepath = cfg["file"]
        label = cfg["table_label"]
        KnowledgeModel = cfg["model"]
        VariantModel = cfg["variant_model"]
        KeywordModel = cfg["keyword_model"]

        if not os.path.exists(filepath):
            print(f"  [WARN] 文件不存在: {filepath}")
            return 0

        df = pd.read_excel(filepath, sheet_name=cfg["sheet"])
        print(f"\n[导入] {label}知识库 ({biz_key}): {len(df)} 条")

        # --- 全量替换: 先删除旧变体/关键词/知识主表 ---
        old_kb = (await db.execute(select(func.count(KnowledgeModel.id)))).scalar()
        old_v = (await db.execute(select(func.count(VariantModel.id)))).scalar()
        old_kw = (await db.execute(select(func.count(KeywordModel.id)))).scalar()
        await db.execute(delete(VariantModel))
        await db.execute(delete(KeywordModel))
        await db.execute(delete(KnowledgeModel))
        print(f"  [清理] 旧数据: 知识{old_kb}条, 变体{old_v}条, 关键词{old_kw}条")

        inserted = 0

        for idx, row in df.iterrows():
            try:
                # --- 按列位置读取 (避免编码问题) ---
                knowledge_code = self._s(row, 0)   # 知识编码
                product_module = self._s(row, 1)    # 产品模块
                title = self._s(row, 2)             # 标题
                category = self._s(row, 3)          # 知识主题
                standard_question = self._s(row, 4) # 标准问法
                common_phrasings = self._s(row, 5)  # 相似问法
                standard_answer = self._s(row, 6)   # 标准答案
                polished_answer = self._s(row, 7)   # 润色后
                # col 8: 是否需要识别品牌 (三业务暂不用)
                # col 9: 是否需要追问 (三业务暂不用)
                is_transfer = self._s(row, 10)      # 是否对客转人工
                status_raw = self._s(row, 11)       # 状态
                transfer_prompt = self._s(row, 12)  # 答复策略

                if not knowledge_code or not standard_question:
                    continue

                # --- 值转换 ---
                # 是否对客转人工: "是" → auto_reply=False (转人工)
                auto_reply = not (is_transfer in ("是", "1", "yes", "true"))

                # 状态映射
                status_map = {"已发布": "published", "待审核": "reviewing", "待完善": "draft"}
                status = status_map.get(status_raw, "published")

                # --- 插入新记录 ---
                knowledge = KnowledgeModel(
                    knowledge_code=knowledge_code,
                    category=category,
                    standard_question=standard_question,
                    common_phrasings=common_phrasings,
                    standard_answer=standard_answer,
                    polished_answer=polished_answer or None,
                    auto_reply=auto_reply,
                    transfer_prompt=transfer_prompt or None,
                    status=status,
                )
                db.add(knowledge)
                await db.flush()
                inserted += 1

                # --- 变体 ---
                if common_phrasings:
                    variants = [v.strip() for v in re.split(r"[;；,，\n]", common_phrasings) if v.strip()]
                    for v in variants:
                        db.add(VariantModel(
                            knowledge_id=knowledge.id,
                            variant_text=v,
                            source="import",
                        ))

                # --- 关键词: 从标准问法+标准答案中提取 ---
                kw_source = f"{standard_question} {standard_answer}"
                keywords = jieba.cut(kw_source)
                seen = set()
                for kw in keywords:
                    kw = kw.strip()
                    if len(kw) >= 2 and kw not in seen:
                        seen.add(kw)
                        db.add(KeywordModel(
                            knowledge_id=knowledge.id,
                            keyword=kw,
                            weight=2 if kw in standard_question else 1,
                        ))

            except Exception as e:
                print(f"  [WARN] 第{idx+1}行导入失败: {e}")
                continue

        self.stats[biz_key] = {"inserted": inserted, "old": old_kb}
        print(f"  [OK] {label}: 新增 {inserted} 条 (旧{old_kb}条已清除)")

    # ============================================
    # FAQ 卡片生成 (每业务从知识条目中取前6条)
    # ============================================
    async def generate_faq_cards(self, db: AsyncSession, biz_key: str):
        """为每个业务生成FAQ卡片"""
        cfg = BIZ_CONFIG[biz_key]
        KnowledgeModel = cfg["model"]
        FaqModel = cfg["faq_model"]
        label = cfg["table_label"]

        # 清除旧卡片
        result = await db.execute(delete(FaqModel))
        print(f"  [清理] {label} 旧FAQ卡片: {result.rowcount} 条")

        # 取前6条已发布的知识作为FAQ
        result = await db.execute(
            select(KnowledgeModel)
            .where(KnowledgeModel.status == "published")
            .limit(6)
        )
        knowledge_list = result.scalars().all()

        card_count = 0
        for i, k in enumerate(knowledge_list):
            card_code = f"{biz_key.upper()}_FAQ_{i+1:03d}"
            db.add(FaqModel(
                card_code=card_code,
                title=k.standard_question,
                knowledge_id=k.id,
                category=k.category,
                display_order=i,
                is_active=True,
            ))
            card_count += 1

        print(f"  [OK] {label}: 生成 {card_count} 条FAQ卡片")

    # ============================================
    # 有为设备明细导入
    # ============================================
    async def import_youwei_devices(self, db: AsyncSession):
        """导入有为设备10010台明细 → youwei_device 表

        Excel结构 (2列):
          Col 0: SIM卡号/设备终端号 → sim_no_11
          Col 1: 行车记录仪ID → terminal_id (用于品牌匹配的关联键)
        """
        if not os.path.exists(YOUWEI_FILE):
            print(f"  [WARN] 文件不存在: {YOUWEI_FILE}")
            return

        df = pd.read_excel(YOUWEI_FILE, sheet_name=YOUWEI_SHEET)
        print(f"\n[导入] 有为设备明细: {len(df)} 条")

        # 清空旧数据
        result = await db.execute(delete(YouweiDevice))
        print(f"  [清理] 旧有为设备数据: {result.rowcount} 条")

        inserted = 0
        batch_size = 500

        for idx, row in df.iterrows():
            try:
                sim_terminal = self._s(row, 0)   # SIM卡号/设备终端号
                recorder_id = self._s(row, 1)     # 行车记录仪ID

                if not recorder_id:
                    continue

                db.add(YouweiDevice(
                    terminal_id=str(recorder_id).strip(),
                    sim_no_11=str(sim_terminal).strip() if sim_terminal else None,
                ))
                inserted += 1

                if inserted % batch_size == 0:
                    await db.flush()
                    print(f"  已处理 {inserted}/{len(df)} 条...")

            except Exception as e:
                print(f"  [WARN] 第{idx+1}行导入失败: {e}")
                continue

        self.stats["youwei"] = inserted
        print(f"  [OK] 有为设备明细: 导入 {inserted} 条")

    # ============================================
    # 辅助方法
    # ============================================
    @staticmethod
    def _s(row, col_idx: int) -> str:
        """按列位置安全读取字符串, NaN返回空"""
        try:
            val = row.iloc[col_idx]
        except (IndexError, KeyError):
            return ""
        if pd.isna(val):
            return ""
        return str(val).strip()

    def print_summary(self):
        print("\n" + "=" * 50)
        print("[导入汇总]")
        for key, val in self.stats.items():
            if isinstance(val, dict):
                if "inserted" in val and val.get("old"):
                    print(f"  {key}: {val['inserted']} 条 (旧{val['old']}条已清除)")
                else:
                    print(f"  {key}: {val['inserted']} 条")
            else:
                print(f"  {key}: {val} 条")
        print("=" * 50)


async def main():
    print("*** 多业务知识库 + 有为设备导入 ***")
    print(f"   数据目录: {KB_DIR}")

    importer = MultiBusinessImporter()

    factory = get_session_factory()
    async with factory() as db:
        # 1. 导入三个业务的知识库
        for biz_key in ["wifi", "data", "refueling"]:
            await importer.import_kb(db, biz_key)
            await db.flush()
            await importer.generate_faq_cards(db, biz_key)
            await db.flush()

        # 2. 导入有为设备明细
        await importer.import_youwei_devices(db)

        # 3. 统一提交
        await db.commit()

    importer.print_summary()
    print("\n*** 全部导入完成! ***")


if __name__ == "__main__":
    asyncio.run(main())
