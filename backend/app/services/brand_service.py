# 品牌识别服务
# 4级优先级链: 精确查表 → 格式规则 → MCU验证 → 人工兜底

import re
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BrandInfo, BrandMapping, OperationalDevice


@dataclass
class BrandResult:
    """品牌识别结果"""
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    brand_code: Optional[str] = None
    confidence: float = 0.0
    path: str = "unknown"               # exact_lookup/format_rule/mcu_verify/human_fallback
    matched_rule: Optional[str] = None
    prompt: Optional[str] = None        # 识别失败时的引导语


class BrandIdentificationService:
    """品牌识别服务 — 4级优先级链

    优先级:
    1. 精确查表 (brand_mapping): VIN前缀/终端号前缀/设备型号 → 置信度 ≥ 0.95
    2. 格式规则匹配 (brand_info.id_format_rules): 正则表达式 → 置信度 ≥ 0.80
    3. MCU验证 (operational_device.mcu_version): → 置信度 ≥ 0.60
    4. 人工兜底: 引导用户提供更多信息或转人工
    """

    # 品牌简称映射 (来自知识库 03_品牌识别规则)
    BRAND_KEYWORDS: Dict[str, str] = {
        "极目": "极目(GPS+BD)",
        "极目单北斗": "极目单北斗(DBD)",
        "航天": "航天",
        "雅迅": "雅迅",
        "启明": "启明",
        "有为": "有为",
        "通用": "通用",
        "鱼快": "极目(GPS+BD)",
        "极目双模": "极目(GPS+BD)",
        "极目北斗": "极目单北斗(DBD)",
    }

    async def identify(
        self,
        db: AsyncSession,
        user_input: str = "",
        collected_info: Optional[Dict] = None,
    ) -> BrandResult:
        """
        识别设备品牌

        Args:
            db: 数据库会话
            user_input: 用户输入 (可能包含品牌名、VIN、终端号等)
            collected_info: 已收集的信息 {vin, terminal_id, sim_iccid, ...}

        Returns:
            BrandResult: 识别结果
        """
        collected_info = collected_info or {}

        # Level 1: 精确查表
        result = await self._exact_table_lookup(db, user_input, collected_info)
        if result.confidence >= 0.95:
            return result

        # Level 2: 格式规则匹配
        result = await self._format_rule_matching(db, user_input, collected_info)
        if result.confidence >= 0.80:
            return result

        # Level 3: MCU验证
        result = await self._mcu_verification(db, user_input, collected_info)
        if result.confidence >= 0.60:
            return result

        # Level 4: 人工兜底
        return BrandResult(
            confidence=0.0,
            path="human_fallback",
            prompt="无法自动识别您的设备品牌。请提供设备型号、终端号或车架号(VIN), 我将帮您进一步确认。",
        )

    async def identify_by_keyword(self, user_input: str) -> Optional[BrandResult]:
        """从用户输入文本中提取品牌关键词 (快速通道)"""
        for keyword, brand_name in self.BRAND_KEYWORDS.items():
            if keyword in user_input:
                return BrandResult(
                    brand_name=brand_name,
                    confidence=0.85,
                    path="keyword_match",
                    matched_rule=f"用户输入包含品牌关键词: {keyword}",
                )
        return None

    async def _exact_table_lookup(
        self, db: AsyncSession, user_input: str, collected_info: Dict
    ) -> BrandResult:
        """Level 1: 在 brand_mapping 表中精确匹配"""
        # 提取可能的标识值
        identifiers = self._extract_identifiers(user_input, collected_info)

        for ident_type, ident_value in identifiers:
            if not ident_value:
                continue

            # 查询 brand_mapping
            stmt = select(BrandMapping).where(
                BrandMapping.match_type == ident_type,
                BrandMapping.match_value == ident_value[:len(BrandMapping.match_value)],
            )
            result = await db.execute(stmt)
            mapping = result.scalar_one_or_none()

            if mapping:
                # 获取品牌信息
                brand_stmt = select(BrandInfo).where(BrandInfo.id == mapping.brand_id)
                brand_result = await db.execute(brand_stmt)
                brand = brand_result.scalar_one_or_none()
                if brand:
                    return BrandResult(
                        brand_id=brand.id,
                        brand_name=brand.brand_name,
                        brand_code=brand.brand_code,
                        confidence=0.95,
                        path="exact_lookup",
                        matched_rule=f"{ident_type}={ident_value[:6]}...",
                    )

        return BrandResult(confidence=0.0)

    async def _format_rule_matching(
        self, db: AsyncSession, user_input: str, collected_info: Dict
    ) -> BrandResult:
        """Level 2: 用 brand_info.id_format_rules 中的正则表达式匹配"""
        # 提取VIN
        vin = collected_info.get("vin", "")
        if not vin:
            vin = self._extract_vin(user_input)

        if not vin:
            return BrandResult(confidence=0.0)

        # 获取所有品牌的格式规则
        stmt = select(BrandInfo).where(
            BrandInfo.is_active == True,
            BrandInfo.id_format_rules.isnot(None),
        ).order_by(BrandInfo.priority)

        result = await db.execute(stmt)
        brands = result.scalars().all()

        for brand in brands:
            rules = brand.id_format_rules or {}
            vin_pattern = rules.get("vin_pattern", "")
            if vin_pattern and re.search(vin_pattern, vin, re.IGNORECASE):
                return BrandResult(
                    brand_id=brand.id,
                    brand_name=brand.brand_name,
                    brand_code=brand.brand_code,
                    confidence=0.80,
                    path="format_rule",
                    matched_rule=f"VIN匹配规则: {vin_pattern}",
                )

        return BrandResult(confidence=0.0)

    async def _mcu_verification(
        self, db: AsyncSession, user_input: str, collected_info: Dict
    ) -> BrandResult:
        """Level 3: 通过 operational_device 中的 MCU版本验证"""
        identifiers = self._extract_identifiers(user_input, collected_info)

        for ident_type, ident_value in identifiers:
            if not ident_value or ident_type not in ("vin", "terminal_id"):
                continue

            # 查询运营平台
            field = "vin" if ident_type == "vin" else "terminal_id"
            stmt = select(OperationalDevice).where(
                getattr(OperationalDevice, field) == ident_value
            ).limit(1)

            result = await db.execute(stmt)
            device = result.scalar_one_or_none()

            if device and device.brand_id:
                brand_stmt = select(BrandInfo).where(BrandInfo.id == device.brand_id)
                brand_result = await db.execute(brand_stmt)
                brand = brand_result.scalar_one_or_none()
                if brand:
                    return BrandResult(
                        brand_id=brand.id,
                        brand_name=brand.brand_name,
                        brand_code=brand.brand_code,
                        confidence=0.65,
                        path="mcu_verify",
                        matched_rule=f"运营平台匹配: {field}={ident_value}",
                    )

        return BrandResult(confidence=0.0)

    # ============================================
    # 辅助方法
    # ============================================

    @staticmethod
    def _extract_identifiers(user_input: str, collected_info: Dict) -> List[tuple]:
        """从用户输入和已收集信息中提取标识符"""
        identifiers = []

        # 从 collected_info 获取
        for key in ["vin", "terminal_id", "sim_iccid", "plate_number"]:
            val = collected_info.get(key, "")
            if val:
                field_map = {
                    "vin": "vin_prefix",
                    "terminal_id": "terminal_prefix",
                    "sim_iccid": "sim_iccid",
                    "plate_number": "plate_number",
                }
                identifiers.append((field_map.get(key, key), str(val)))

        # 从用户输入提取 VIN (17位字母数字组合)
        vin_match = re.search(r"[A-HJ-NPR-Z0-9]{17}", user_input, re.IGNORECASE)
        if vin_match:
            identifiers.append(("vin_prefix", vin_match.group().upper()))

        # 从用户输入提取终端号 (常见格式: 数字字母组合)
        terminal_match = re.search(r"[A-Z0-9]{10,20}", user_input)
        if terminal_match:
            identifiers.append(("terminal_prefix", terminal_match.group().upper()))

        return identifiers

    @staticmethod
    def _extract_vin(text: str) -> str:
        """从文本提取VIN"""
        match = re.search(r"[A-HJ-NPR-Z0-9]{17}", text, re.IGNORECASE)
        return match.group().upper() if match else ""
