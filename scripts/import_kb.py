# Excel 知识库导入脚本
# 用法: python scripts/import_kb.py
# 将行车记录仪Agent知识库_更新版618.xlsx 的5个Sheet导入MySQL

import sys
import os
import asyncio
import re
import json
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pandas as pd
import jieba
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_session_factory
from app.core.config import settings
from app.models import (
    KnowledgeAnswer,
    KnowledgeQuestionVariant,
    KnowledgeKeyword,
    KnowledgeAttachment,
    QueryIntentConfig,
    BrandInfo,
    BrandMapping,
    FieldDictionary,
    SystemConfig,
)


class KnowledgeBaseImporter:
    """知识库导入器 — Excel 5 Sheets → MySQL"""

    def __init__(self):
        self.stats = {sheet: 0 for sheet in ["01_知识问答库", "02_查询问题库", "03_品牌识别规则", "04_运营字段字典", "00_使用说明"]}
        self.today = datetime.now().strftime("%Y%m%d")

    async def import_all(self, excel_path: str):
        """导入全部5个Sheet"""
        if not os.path.exists(excel_path):
            print(f"❌ 文件不存在: {excel_path}")
            return

        sheets = pd.read_excel(excel_path, sheet_name=None)
        print(f"📄 读取到 {len(sheets)} 个Sheet: {list(sheets.keys())}")

        async with get_session_factory()() as db:
            await self._import_sheet_01(db, sheets.get("01_知识问答库"))
            await self._import_sheet_02(db, sheets.get("02_查询问题库"))
            await self._import_sheet_03(db, sheets.get("03_品牌识别规则"))
            await self._import_sheet_04(db, sheets.get("04_运营字段字典"))
            await self._import_sheet_00(db, sheets.get("00_使用说明"))
            await db.commit()

        self._print_stats()

    async def _import_sheet_01(self, db: AsyncSession, df: pd.DataFrame):
        """导入 01_知识问答库 (144条) → knowledge_answer + variants + keywords + attachments"""
        if df is None:
            print("⚠️ 未找到 01_知识问答库 Sheet")
            return

        print(f"\n📥 导入 01_知识问答库 ({len(df)} 条)...")
        count = 0

        for _, row in df.iterrows():
            try:
                # 清洗数据
                knowledge_code = self._safe_str(row.get("知识编号", ""))
                if not knowledge_code:
                    knowledge_code = f"KA-{self.today}-{count+1:06d}"

                standard_question = self._safe_str(row.get("标准问题", ""))
                standard_answer = self._safe_str(row.get("标准答案", ""))
                if not standard_question or not standard_answer:
                    continue

                # 解析分类
                product_module = self._safe_str(row.get("产品模块", ""))
                manufacturer = self._safe_str(row.get("厂家", ""))
                knowledge_type = self._safe_str(row.get("知识类型", ""))

                # 是否需要品牌
                need_brand_str = self._safe_str(row.get("是否需要识别品牌", "否"))
                need_brand = need_brand_str in ("是", "1", "yes", "true")

                # 是否需要附件
                need_attachment_str = self._safe_str(row.get("是否需要附件", "否"))
                need_attachment = need_attachment_str in ("是", "1", "yes", "true")

                # 回答类型
                answer_type = self._safe_str(row.get("回答类型", "text")) or "text"

                # 状态
                status = self._safe_str(row.get("状态", "draft")) or "draft"
                status_map = {"已发布": "published", "待审核": "reviewing", "待完善": "draft"}
                status = status_map.get(status, status)

                # 来源
                source = self._safe_str(row.get("来源备注", ""))

                # 创建知识条目
                knowledge = KnowledgeAnswer(
                    knowledge_code=knowledge_code,
                    business_area="dashcam",
                    category_l1=product_module,
                    category_l2=knowledge_type,
                    manufacturer=manufacturer if manufacturer != "通用" else None,
                    standard_question=standard_question,
                    standard_answer=standard_answer,
                    answer_type=answer_type,
                    need_brand=need_brand,
                    need_attachment=need_attachment,
                    risk_level="low",
                    auto_reply=True,
                    status=status,
                    version=1,
                    source_file=source,
                )
                db.add(knowledge)
                await db.flush()  # 获取 knowledge.id

                # 导入问法变体
                common_phrasings = self._safe_str(row.get("常见问法", ""))
                if common_phrasings:
                    variants = [v.strip() for v in re.split(r"[;；,，\n]", common_phrasings) if v.strip()]
                    for v in variants:
                        db.add(KnowledgeQuestionVariant(
                            knowledge_id=knowledge.id,
                            variant_text=v,
                            source="import",
                        ))

                # 提取关键词
                keywords = jieba.cut(standard_question)
                seen_keywords = set()
                for kw in keywords:
                    kw = kw.strip()
                    if len(kw) >= 2 and kw not in seen_keywords:
                        seen_keywords.add(kw)
                        db.add(KnowledgeKeyword(
                            knowledge_id=knowledge.id,
                            keyword=kw,
                            keyword_type="normal",
                            weight=2,
                        ))

                # 导入附件 (如果有)
                attachment_urls = self._safe_str(row.get("附件URL", "")) or self._safe_str(row.get("附件", ""))
                if attachment_urls and need_attachment:
                    urls = [u.strip() for u in re.split(r"[;；,\n]", attachment_urls) if u.strip()]
                    for i, url in enumerate(urls):
                        db.add(KnowledgeAttachment(
                            knowledge_id=knowledge.id,
                            file_name=f"附件_{i+1}",
                            file_type=self._guess_file_type(url),
                            file_url=url,
                            display_order=i,
                        ))

                count += 1
                if count % 20 == 0:
                    print(f"  已处理 {count}/{len(df)} 条...")

            except Exception as e:
                print(f"  ⚠️ 第{count+1}行导入失败: {e}")
                continue

        self.stats["01_知识问答库"] = count
        print(f"  ✅ 01_知识问答库 导入完成: {count} 条")

    async def _import_sheet_02(self, db: AsyncSession, df: pd.DataFrame):
        """导入 02_查询问题库 (13条) → query_intent_config"""
        if df is None:
            print("⚠️ 未找到 02_查询问题库 Sheet")
            return

        print(f"\n📥 导入 02_查询问题库 ({len(df)} 条)...")
        count = 0

        for _, row in df.iterrows():
            try:
                query_code = self._safe_str(row.get("查询编号", ""))
                if not query_code:
                    continue

                display_name = self._safe_str(row.get("查询意图", ""))
                required_info = self._safe_str(row.get("用户必填信息", ""))
                match_conditions = self._safe_str(row.get("匹配条件", ""))
                return_fields = self._safe_str(row.get("返回字段", ""))
                reply_normal = self._safe_str(row.get("正常回复模板", ""))
                reply_empty = self._safe_str(row.get("空值/未匹配回复模板", ""))
                transfer_rule = self._safe_str(row.get("转人工规则", ""))
                auto_reply_str = self._safe_str(row.get("是否允许自动回复", "是"))
                auto_reply = auto_reply_str in ("是", "1", "yes", "true")

                # 解析槽位
                slots = self._parse_slots(required_info)
                # 解析匹配条件
                conditions = self._parse_conditions(match_conditions)
                # 解析返回字段
                ret_fields = self._parse_return_fields(return_fields)

                db.add(QueryIntentConfig(
                    query_type_code=query_code,
                    display_name=display_name,
                    business_area="dashcam",
                    required_slots=slots,
                    data_source="operational_db",
                    match_conditions=conditions,
                    return_fields=ret_fields,
                    reply_template_normal=reply_normal,
                    reply_template_empty=reply_empty,
                    escalation_rule={"max_retry": 2, "empty_transfer": True},
                    auto_reply=auto_reply,
                    is_active=True,
                ))
                count += 1

            except Exception as e:
                print(f"  ⚠️ 第{count+1}行导入失败: {e}")
                continue

        self.stats["02_查询问题库"] = count
        print(f"  ✅ 02_查询问题库 导入完成: {count} 条")

    async def _import_sheet_03(self, db: AsyncSession, df: pd.DataFrame):
        """导入 03_品牌识别规则 (7条) → brand_info + brand_mapping"""
        if df is None:
            print("⚠️ 未找到 03_品牌识别规则 Sheet")
            return

        print(f"\n📥 导入 03_品牌识别规则 ({len(df)} 条)...")
        count = 0

        for _, row in df.iterrows():
            try:
                brand_name = self._safe_str(row.get("品牌", ""))
                if not brand_name:
                    continue

                priority_str = self._safe_str(row.get("优先级", "99"))
                try:
                    priority = int(priority_str)
                except ValueError:
                    priority = 99

                rule_text = self._safe_str(row.get("主判断规则", ""))
                secondary_rule = self._safe_str(row.get("二次判断/数据源", ""))
                auto_condition = self._safe_str(row.get("自动识别条件", ""))

                brand = BrandInfo(
                    brand_code=f"BRAND_{priority:02d}",
                    brand_name=brand_name,
                    short_name=brand_name.split("（")[0] if "（" in brand_name else brand_name,
                    aliases=self._parse_brand_aliases(brand_name, auto_condition),
                    business_area="dashcam",
                    priority=priority,
                    id_format_rules=self._parse_format_rules(rule_text),
                    mcu_verify_rule=secondary_rule if secondary_rule else None,
                    is_active=True,
                )
                db.add(brand)
                await db.flush()

                # 导入VIN前缀映射 (从规则文本中提取)
                vin_prefixes = self._extract_vin_prefixes(rule_text)
                for prefix in vin_prefixes:
                    db.add(BrandMapping(
                        brand_id=brand.id,
                        match_type="vin_prefix",
                        match_value=prefix,
                        description=f"{brand_name} VIN前缀",
                    ))

                count += 1

            except Exception as e:
                print(f"  ⚠️ 第{count+1}行导入失败: {e}")
                continue

        self.stats["03_品牌识别规则"] = count
        print(f"  ✅ 03_品牌识别规则 导入完成: {count} 条")

    async def _import_sheet_04(self, db: AsyncSession, df: pd.DataFrame):
        """导入 04_运营字段字典 (22条) → field_dictionary"""
        if df is None:
            print("⚠️ 未找到 04_运营字段字典 Sheet")
            return

        print(f"\n📥 导入 04_运营字段字典 ({len(df)} 条)...")
        count = 0

        for _, row in df.iterrows():
            try:
                backend_field = self._safe_str(row.get("运营平台字段", ""))
                display_name = self._safe_str(row.get("业务含义", ""))
                if not backend_field:
                    continue

                can_show_str = self._safe_str(row.get("是否允许对客展示", "否"))
                can_show = can_show_str in ("是", "1", "yes", "true", "允许")

                driver_lang = self._safe_str(row.get("司机常用语言/替换词", ""))
                agent_usage = self._safe_str(row.get("Agent用途", ""))
                usage_note = self._safe_str(row.get("使用说明", ""))

                db.add(FieldDictionary(
                    backend_field=backend_field,
                    display_name=display_name or driver_lang,
                    business_area="dashcam",
                    field_type="string",
                    can_show_customer=can_show,
                    description=usage_note or agent_usage,
                ))
                count += 1

            except Exception as e:
                print(f"  ⚠️ 第{count+1}行导入失败: {e}")
                continue

        self.stats["04_运营字段字典"] = count
        print(f"  ✅ 04_运营字段字典 导入完成: {count} 条")

    async def _import_sheet_00(self, db: AsyncSession, df: pd.DataFrame):
        """导入 00_使用说明 → system_config (存档参考)"""
        if df is None:
            print("⚠️ 未找到 00_使用说明 Sheet")
            return

        print(f"\n📥 导入 00_使用说明 ({len(df)} 条)...")

        # 将使用说明合并为文本存档
        content_lines = []
        for _, row in df.iterrows():
            for col in df.columns:
                val = self._safe_str(row.get(col, ""))
                if val:
                    content_lines.append(f"[{col}] {val}")

        db.add(SystemConfig(
            config_key="kb_usage_guide",
            config_value="\n".join(content_lines),
            config_type="text",
            description="知识库使用说明 (来自Excel 00_使用说明 Sheet)",
            is_editable=False,
        ))

        self.stats["00_使用说明"] = 1
        print(f"  ✅ 00_使用说明 存档完成")

    # ============================================
    # 辅助方法
    # ============================================

    @staticmethod
    def _safe_str(val) -> str:
        """安全转换为字符串, NaN返回空"""
        if pd.isna(val):
            return ""
        return str(val).strip()

    @staticmethod
    def _guess_file_type(url: str) -> str:
        """从URL推断文件类型"""
        url_lower = url.lower()
        if any(ext in url_lower for ext in [".mp4", ".avi", ".mov", ".wmv"]):
            return "video"
        if any(ext in url_lower for ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp"]):
            return "image"
        if any(ext in url_lower for ext in [".pdf", ".doc", ".docx"]):
            return "document"
        return "link"

    @staticmethod
    def _parse_slots(required_info: str) -> list:
        """解析用户必填信息为槽位配置"""
        if not required_info:
            return []
        slots = []
        items = re.split(r"[;；,，、\n]", required_info)
        for item in items:
            item = item.strip()
            if not item:
                continue
            field = "vin" if "VIN" in item.upper() or "车架" in item else \
                    "terminal_id" if "终端" in item else \
                    "sim_iccid" if "SIM" in item.upper() else \
                    "plate_number" if "车牌" in item else "unknown"
            slots.append({
                "field": field,
                "display": item,
                "type": "string",
                "collect_prompt": f"请提供您的{item}",
            })
        return slots

    @staticmethod
    def _parse_conditions(conditions_str: str) -> list:
        """解析匹配条件"""
        if not conditions_str:
            return []
        # 简单格式: "vin=用户输入" → {"field":"vin","op":"eq","value":"{{slot.vin}}"}
        conditions = []
        parts = re.split(r"[;；,\n]", conditions_str)
        for part in parts:
            part = part.strip()
            if "=" in part:
                field, _ = part.split("=", 1)
                field = field.strip().lower()
                conditions.append({
                    "field": field,
                    "op": "eq",
                    "value": f"{{{{slot.{field}}}}}",
                })
        return conditions

    @staticmethod
    def _parse_return_fields(fields_str: str) -> list:
        """解析返回字段"""
        if not fields_str:
            return []
        fields = []
        items = re.split(r"[;；,，\n]", fields_str)
        for item in items:
            item = item.strip()
            if item:
                fields.append({"backend": item, "display": item})
        return fields

    @staticmethod
    def _parse_brand_aliases(brand_name: str, auto_condition: str) -> list:
        """解析品牌别名"""
        aliases = [brand_name]
        # 提取括号外的简称
        if "（" in brand_name:
            short = brand_name.split("（")[0]
            if short != brand_name:
                aliases.append(short)
        return aliases

    @staticmethod
    def _parse_format_rules(rule_text: str) -> dict:
        """从规则文本提取格式规则"""
        if not rule_text:
            return {}
        rules = {"raw_rule": rule_text}
        # 尝试提取VIN前缀模式
        vin_match = re.search(r"[A-Z0-9]{3,}", rule_text)
        if vin_match:
            rules["vin_pattern"] = vin_match.group()
        return rules

    @staticmethod
    def _extract_vin_prefixes(rule_text: str) -> list:
        """从规则文本提取VIN前缀"""
        if not rule_text:
            return []
        prefixes = re.findall(r"[A-Z0-9]{3,6}", rule_text)
        return list(set(prefixes))[:10]  # 最多10个

    def _print_stats(self):
        """打印导入统计"""
        print("\n" + "=" * 50)
        print("📊 导入统计:")
        total = 0
        for sheet, count in self.stats.items():
            print(f"  {sheet}: {count} 条")
            total += count
        print(f"  {'总计':>20}: {total} 条")
        print("=" * 50)


async def main():
    excel_path = str(settings.KB_EXCEL_PATH)
    print(f"📂 知识库文件: {excel_path}")

    importer = KnowledgeBaseImporter()
    await importer.import_all(excel_path)


if __name__ == "__main__":
    asyncio.run(main())
