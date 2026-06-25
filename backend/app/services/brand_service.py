# 品牌识别服务
# 优先级链: 精确查表 → 格式规则 → operational_data/终端号规则 → 人工兜底

import re
from typing import Dict, Optional, List
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import BrandInfo, BrandMapping, YouweiDevice, OperationalData


@dataclass
class BrandResult:
    """品牌识别结果"""
    brand_id: Optional[int] = None
    brand_name: Optional[str] = None
    brand_code: Optional[str] = None
    confidence: float = 0.0
    path: str = "unknown"               # exact_lookup/format_rule/operational_data/human_fallback
    matched_rule: Optional[str] = None
    prompt: Optional[str] = None        # 识别失败时的引导语


class BrandIdentificationService:
    """品牌识别服务

    优先级:
    1. 精确查表 (brand_mapping): VIN前缀/终端号前缀/设备型号 → 置信度 ≥ 0.95
    2. 格式规则匹配 (brand_info.id_format_rules): 正则表达式 → 置信度 ≥ 0.80
    3. operational_data + 终端号规则: VIN 查品牌/终端号, 再结合 youwei_device 二次识别
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

        # Level 3: 人工兜底
        return BrandResult(
            confidence=0.0,
            path="human_fallback",
            prompt="无法自动识别您的设备品牌。请提供设备型号、终端号或车架号(VIN), 我将帮您进一步确认。",
        )

    async def identify_by_keyword(self, user_input: str) -> Optional[BrandResult]:
        """从用户输入文本中提取品牌关键词 (快速通道)"""
        for keyword, brand_name in sorted(self.BRAND_KEYWORDS.items(), key=lambda item: len(item[0]), reverse=True):
            if keyword in user_input:
                if keyword == "鱼快":
                    return BrandResult(
                        brand_name=None,
                        confidence=0.6,
                        path="keyword_ambiguous",
                        matched_rule="用户输入包含鱼快, 需结合VIN/终端号区分极目/有为",
                        prompt="鱼快设备需结合车架号(VIN)或终端号确认具体厂家。",
                    )
                return BrandResult(
                    brand_name=brand_name,
                    confidence=0.85,
                    path="keyword_match",
                    matched_rule=f"用户输入包含品牌关键词: {keyword}",
                )
        return None

    async def identify_by_vin(
        self, db: AsyncSession, vin: str
    ) -> Optional[BrandResult]:
        """VIN+终端号 双因子联合品牌识别

        VIN查品牌有可能出错, 终端号规则更可靠 → 二者结合:
        1. 查 operational_data → 拿到 device_brand + recorder_id(行车记录仪ID)
        2. 用 recorder_id 跑终端号规则 (优先, 更可靠)
        3. 终端号命中 → 返回 (若与VIN结果一致则提升置信度)
        4. 终端号未命中 → 回退VIN查表逻辑
        5. 离线表查不到 → 调接口

        Returns:
            BrandResult 或 None(查询失败/VIN不存在)
        """

        result = await db.execute(
            select(OperationalData).where(OperationalData.vin == vin).limit(1)
        )
        op_data = result.scalar_one_or_none()

        if not op_data:
            # 离线表查不到, 尝试调接口 (接口就绪后生效)
            from app.integrations.platform_client import platform_client
            try:
                info = await platform_client.get_device_brand(vin)
            except Exception:
                info = None
            if not info:
                return None
            vin_brand = info.get("brand")
            # 接口返回的终端号: recorder_id 或 terminal_id
            tid = info.get("recorder_id") or info.get("terminal_id")
        else:
            vin_brand = op_data.device_brand
            # 行车记录仪ID (recorder_id) 优先, 设备终端号做fallback
            tid = op_data.recorder_id or op_data.terminal_id

        # ============================================
        # 终端号规则识别 (优先, 比VIN查品牌更可靠)
        # ============================================
        tid_result = await self.identify_by_terminal_id(db, tid)

        if tid_result:
            # 终端号命中 → 若VIN结果一致则提升置信度
            if vin_brand:
                vin_mapped = self._map_vin_brand(vin_brand)
                if vin_mapped and vin_mapped == tid_result.brand_name:
                    tid_result.confidence = min(tid_result.confidence + 0.05, 1.0)
                    tid_result.path = f"vin_terminal_combined({tid_result.path})"
                    tid_result.matched_rule += f"; VIN结果一致({vin_brand})→置信度提升"
                elif vin_mapped:
                    # VIN与终端号不一致 → 终端号优先, 标记差异
                    tid_result.matched_rule += f"; VIN结果={vin_brand}(与终端号不一致,以终端号为准)"
            return tid_result

        # ============================================
        # 终端号未命中 → 回退VIN查表
        # ============================================
        if not vin_brand:
            return None

        # 鱼快 → 二级区分极目/有为
        if vin_brand == "鱼快":
            tid_for_yw = op_data.terminal_id if op_data else tid
            if tid_for_yw:
                yw = (await db.execute(
                    select(YouweiDevice).where(YouweiDevice.terminal_id == str(tid_for_yw))
                )).scalar_one_or_none()
                if yw:
                    return BrandResult(brand_name="有为", confidence=0.9,
                                       path="youwei_lookup",
                                       matched_rule=f"终端号{tid_for_yw}在有为明细表中 → 有为")
            # youwei关联不上, 鱼快暂归极目
            return BrandResult(brand_name="极目(GPS+BD)", confidence=0.7,
                               path="operational_data_yukuai",
                               matched_rule="运营数据品牌=鱼快, youwei未匹配 → 极目(待确认)")

        # 其他品牌直接用
        mapped = self._map_vin_brand(vin_brand)
        if mapped:
            return BrandResult(brand_name=mapped, confidence=0.90,
                               path="operational_data_vin_only",
                               matched_rule=f"运营数据品牌: {vin_brand}(无终端号验证)")
        return None

    @staticmethod
    def _map_vin_brand(brand: str) -> Optional[str]:
        """运营数据 device_brand → 标准品牌名映射"""
        brand_map = {
            "航天": "航天", "雅迅": "雅迅", "启明": "启明", "锐明": "锐明",
            "极目": "极目(GPS+BD)", "有为": "有为", "鱼快": "极目(GPS+BD)",
        }
        return brand_map.get(brand)

    async def identify_by_terminal_id(
        self, db: AsyncSession, terminal_id: Optional[str]
    ) -> Optional[BrandResult]:
        """通过行车记录仪ID识别品牌 (5品牌规则, 不依赖VIN)

        规则优先级 (高→低):
        1. 有为: 查youwei_device明细表 (全量10010台, 最确定)
        2. 雅迅: 00开头纯数字
        3. 启明: 31开头纯数字
        4. 极目: 7位纯数字(95%) / 第1或2位是A其余数字(5%)
        5. 航天: 数字字母混合(95%) / 90或91开头纯数字

        Args:
            db: 数据库会话
            terminal_id: 行车记录仪ID (recorder_id 或 terminal_id)

        Returns:
            BrandResult 或 None(规则未命中)
        """
        if not terminal_id:
            return None

        tid = str(terminal_id).strip().upper()
        if not tid:
            return None

        # 1. 有为: DB查明细表 (最确定)
        yw = (await db.execute(
            select(YouweiDevice).where(YouweiDevice.terminal_id == tid).limit(1)
        )).scalar_one_or_none()
        if yw:
            return BrandResult(brand_name="有为", confidence=0.95,
                               path="terminal_id_yw_table",
                               matched_rule=f"终端号{tid}在有为明细表中 → 有为")

        # 2. 雅迅: 00开头纯数字
        if tid.isdigit() and tid.startswith("00"):
            return BrandResult(brand_name="雅迅", confidence=0.95,
                               path="terminal_id_rule",
                               matched_rule=f"终端号{tid}: 00开头纯数字 → 雅迅")

        # 3. 启明: 31开头纯数字
        if tid.isdigit() and tid.startswith("31"):
            return BrandResult(brand_name="启明", confidence=0.95,
                               path="terminal_id_rule",
                               matched_rule=f"终端号{tid}: 31开头纯数字 → 启明")

        # 4. 极目: 7位, 95%纯数字 / 5%第1或2位A其余数字
        if len(tid) == 7:
            if tid.isdigit():
                return BrandResult(brand_name="极目(GPS+BD)", confidence=0.95,
                                   path="terminal_id_rule",
                                   matched_rule=f"终端号{tid}: 7位纯数字 → 极目")
            # 第1位A, 其余数字
            if tid[0] == "A" and tid[1:].isdigit():
                return BrandResult(brand_name="极目(GPS+BD)", confidence=0.90,
                                   path="terminal_id_rule",
                                   matched_rule=f"终端号{tid}: 第1位A其余数字 → 极目")
            # 第2位A, 其余数字 (如 1A34567)
            if len(tid) >= 2 and tid[1] == "A" and tid[0].isdigit() and tid[2:].isdigit():
                return BrandResult(brand_name="极目(GPS+BD)", confidence=0.90,
                                   path="terminal_id_rule",
                                   matched_rule=f"终端号{tid}: 第2位A其余数字 → 极目")

        # 5. 航天: 95%数字字母混合 / 极少90或91开头纯数字
        has_digit = any(c.isdigit() for c in tid)
        has_alpha = any(c.isalpha() for c in tid)
        if has_digit and has_alpha:
            return BrandResult(brand_name="航天", confidence=0.85,
                               path="terminal_id_rule",
                               matched_rule=f"终端号{tid}: 数字字母混合 → 航天")
        if tid.isdigit() and (tid.startswith("90") or tid.startswith("91")):
            return BrandResult(brand_name="航天", confidence=0.80,
                               path="terminal_id_rule",
                               matched_rule=f"终端号{tid}: 90/91开头纯数字 → 航天")

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
