"""Rule-first intent, routing, and handoff decisions.

This module is the shared rule layer for chat.py and LangGraph nodes.  It keeps
normal knowledge retrieval free from noisy keyword-answer matching while still
using keywords where they are reliable: handoff, business routing, and live data
query detection.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from app.nodes.query_judgment import _match_query_type as _fallback_match_query_type


@dataclass(frozen=True)
class TransferDecision:
    should_transfer: bool
    reason_type: str = ""
    reason: str = ""
    priority: str = "normal"
    matched_keyword: Optional[str] = None


@dataclass(frozen=True)
class IntentDecision:
    intent_type: str
    confidence: float
    business_area: str
    query_type_code: Optional[str] = None
    should_clarify: bool = False
    method: str = "rule"


TRANSFER_KEYWORDS = (
    "转人工",
    "人工客服",
    "人工服务",
    "找人工",
    "真人",
    "人工",
    "转接",
    "人工电话",
    "我要找客服",
)

GREETING_PATTERNS = (
    r"^(你好|您好|hi|hello|在吗|在不在|嗨|早上好|下午好|晚上好)",
)

HIGH_RISK_KEYWORDS = (
    "投诉",
    "315",
    "12315",
    "起诉",
    "媒体曝光",
    "曝光",
    "维权",
    "消协",
    "工商",
    "赔偿",
    "欺诈",
    "骗人",
)

REFUND_RISK_MARKERS = (
    "不给退",
    "不退钱",
    "乱扣费",
    "恶意扣费",
    "强制扣费",
    "扣费投诉",
    "退款投诉",
    "要求退款",
    "必须退款",
)

UNSUPPORTED_OPERATIONS = (
    "审核",
    "转网",
    "入网审核",
    "开通审核",
    "写车架号",
    "下发车架号",
    "车辆信息写入",
    "修改车辆资料",
    "修改设备资料",
    "修改绑定",
    "换绑",
    "解绑",
    "激活设备",
    "修改套餐",
    "修改缴费记录",
)

WIFI_MARKERS = ("wifi", "wi-fi", "无线网", "无线网络", "热点", "车内wifi", "随车wifi")
REFUELING_MARKERS = ("加油", "油券", "加油券", "油站", "油价", "油卡", "汽油", "柴油", "燃油")
DATA_STRONG_MARKERS = ("基础流量", "流量包", "流量充值", "基地月包", "流量卡", "流量套餐")
DATA_CONTEXT_MARKERS = ("流量", "青岛", "长春")
DASHCAM_MARKERS = (
    "行车记录仪",
    "记录仪",
    "设备",
    "终端",
    "车架号",
    "vin",
    "北斗",
    "sim卡",
    "卡号",
)

INSTRUCTIONAL_MARKERS = (
    "怎么",
    "如何",
    "怎样",
    "在哪",
    "哪里",
    "方法",
    "步骤",
    "教程",
    "操作",
    "查看方式",
    "查询方式",
    "怎么查询",
    "如何查询",
)

PERSONAL_QUERY_MARKERS = (
    "我的",
    "我这",
    "这台",
    "这辆",
    "本车",
    "帮我查",
    "帮我查询",
    "查一下我的",
    "是多少",
    "什么时候到期",
    "到期了吗",
    "到期时间",
    "在线吗",
    "离线了吗",
    "状态怎么样",
    "现在状态",
    "哪个服务商",
    "哪家服务商",
)

QUERY_INTENT_PATTERNS = (
    (r"(sim|卡号|iccid)", "QRY001"),
    (r"(终端号|设备号|设备id|device.?id)", "QRY002"),
    (r"(sim.*终端|终端.*sim|卡号.*终端|id.*sim)", "QRY003"),
    (r"(服务商|运营商)", "QRY004"),
    (r"(司机卡|驾驶员卡|ic卡)", "QRY005"),
    (r"(车辆信息|车主)", "QRY006"),
    (r"(续费|续约|到期)", "QRY007"),
    (r"(服务到期|到期时间)", "QRY008"),
    (r"(缴费|激活|开通)", "QRY009"),
    (r"(在线|离线|状态)", "QRY010"),
    (r"(品牌|厂家|厂商)", "QRY011"),
    (r"(型号|类型|设备类型)", "QRY012"),
    (r"(流量|套餐|流量卡)", "QRY013"),
)


@dataclass(frozen=True)
class QueryIntentRule:
    keyword: str
    target: str
    is_regex: bool = False


@dataclass(frozen=True)
class RuleConfig:
    transfer_keywords: tuple[str, ...]
    high_risk_keywords: tuple[str, ...]
    refund_risk_markers: tuple[str, ...]
    unsupported_operations: tuple[str, ...]
    wifi_markers: tuple[str, ...]
    refueling_markers: tuple[str, ...]
    data_strong_markers: tuple[str, ...]
    data_context_markers: tuple[str, ...]
    dashcam_markers: tuple[str, ...]
    instructional_markers: tuple[str, ...]
    personal_query_markers: tuple[str, ...]
    query_intent_rules: tuple[QueryIntentRule, ...]

    @classmethod
    def from_defaults(cls) -> "RuleConfig":
        return cls(
            transfer_keywords=TRANSFER_KEYWORDS,
            high_risk_keywords=HIGH_RISK_KEYWORDS,
            refund_risk_markers=REFUND_RISK_MARKERS,
            unsupported_operations=UNSUPPORTED_OPERATIONS,
            wifi_markers=WIFI_MARKERS,
            refueling_markers=REFUELING_MARKERS,
            data_strong_markers=DATA_STRONG_MARKERS,
            data_context_markers=DATA_CONTEXT_MARKERS,
            dashcam_markers=DASHCAM_MARKERS,
            instructional_markers=INSTRUCTIONAL_MARKERS,
            personal_query_markers=PERSONAL_QUERY_MARKERS,
            query_intent_rules=tuple(
                QueryIntentRule(pattern, target, is_regex=True)
                for pattern, target in QUERY_INTENT_PATTERNS
            ),
        )


_rule_config = RuleConfig.from_defaults()


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        value = (item or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _row_metadata(row: Any) -> dict:
    metadata = _row_value(row, "extra_metadata")
    if metadata is None:
        metadata = _row_value(row, "metadata")
    return metadata if isinstance(metadata, dict) else {}


def _collect_keywords(
    rows: Sequence[Any],
    rule_type: str,
    fallback: tuple[str, ...],
    *,
    target: Optional[str] = None,
    match_type: Optional[str] = None,
) -> tuple[str, ...]:
    values: list[str] = []
    for row in rows:
        if _row_value(row, "rule_type") != rule_type:
            continue
        if target is not None and _row_value(row, "target") != target:
            continue
        metadata = _row_metadata(row)
        if match_type is not None and metadata.get("match_type") != match_type:
            continue
        keyword = _row_value(row, "keyword")
        if keyword:
            values.append(str(keyword))
    return _dedupe(values) or fallback


def _collect_query_intent_rules(
    rows: Sequence[Any],
    fallback: tuple[QueryIntentRule, ...],
) -> tuple[QueryIntentRule, ...]:
    rules: list[QueryIntentRule] = []
    for row in rows:
        if _row_value(row, "rule_type") != "query_intent":
            continue
        keyword = _row_value(row, "keyword")
        target = _row_value(row, "target")
        if not keyword or not target:
            continue
        metadata = _row_metadata(row)
        is_regex = (
            _row_value(row, "action") == "regex"
            or metadata.get("match_type") == "regex"
            or metadata.get("regex") is True
        )
        rules.append(QueryIntentRule(str(keyword), str(target), bool(is_regex)))
    return tuple(rules) or fallback


def _build_rule_config_from_rows(rows: Sequence[Any]) -> RuleConfig:
    defaults = RuleConfig.from_defaults()
    return RuleConfig(
        transfer_keywords=_collect_keywords(rows, "transfer", defaults.transfer_keywords),
        high_risk_keywords=_collect_keywords(rows, "high_risk", defaults.high_risk_keywords),
        refund_risk_markers=_collect_keywords(rows, "refund_risk", defaults.refund_risk_markers),
        unsupported_operations=_collect_keywords(
            rows, "unsupported_operation", defaults.unsupported_operations
        ),
        wifi_markers=_collect_keywords(
            rows, "business_route", defaults.wifi_markers, target="wifi"
        ),
        refueling_markers=_collect_keywords(
            rows, "business_route", defaults.refueling_markers, target="refueling"
        ),
        data_strong_markers=_collect_keywords(
            rows, "business_route", defaults.data_strong_markers,
            target="data", match_type="strong"
        ),
        data_context_markers=_collect_keywords(
            rows, "business_route", defaults.data_context_markers,
            target="data", match_type="context"
        ),
        dashcam_markers=_collect_keywords(
            rows, "business_route", defaults.dashcam_markers, target="dashcam"
        ),
        instructional_markers=_collect_keywords(
            rows, "intent_hint", defaults.instructional_markers, target="instructional"
        ),
        personal_query_markers=_collect_keywords(
            rows, "intent_hint", defaults.personal_query_markers, target="personal_query"
        ),
        query_intent_rules=_collect_query_intent_rules(rows, defaults.query_intent_rules),
    )


def apply_keyword_rule_rows(rows: Sequence[Any]) -> int:
    """Apply active keyword_rule rows to the in-memory rule config."""
    global _rule_config
    _rule_config = _build_rule_config_from_rows(rows)
    return len(rows)


def reset_keyword_rules() -> None:
    """Reset in-memory rules to code defaults; useful for tests."""
    global _rule_config
    _rule_config = RuleConfig.from_defaults()


def get_rule_config_snapshot() -> RuleConfig:
    return _rule_config


def get_default_keyword_rule_seed() -> list[dict[str, Any]]:
    """Default keyword_rule rows used for database initialization.

    These rows mirror the code fallback constants. Database rows become the
    primary source after startup loading; constants remain the fallback when the
    table is missing, empty, or partially configured.
    """
    rows: list[dict[str, Any]] = []

    def add(
        rule_type: str,
        keyword: str,
        *,
        target: Optional[str] = None,
        business_area: Optional[str] = None,
        action: Optional[str] = None,
        priority: int = 0,
        metadata: Optional[dict[str, Any]] = None,
        description: Optional[str] = None,
    ) -> None:
        rows.append({
            "rule_type": rule_type,
            "keyword": keyword,
            "business_area": business_area,
            "target": target,
            "action": action,
            "priority": priority,
            "is_active": True,
            "extra_metadata": metadata or {},
            "description": description,
        })

    for keyword in TRANSFER_KEYWORDS:
        add("transfer", keyword, action="transfer", priority=100, description="用户显式要求转人工")
    for keyword in HIGH_RISK_KEYWORDS:
        add("high_risk", keyword, action="transfer", priority=90, description="投诉/维权等高风险表达")
    for keyword in REFUND_RISK_MARKERS:
        add("refund_risk", keyword, action="transfer", priority=90, description="退款争议风险表达")
    for keyword in UNSUPPORTED_OPERATIONS:
        add("unsupported_operation", keyword, action="transfer", priority=80, description="AI不可代办的后台操作")

    for keyword in WIFI_MARKERS:
        add("business_route", keyword, target="wifi", action="route", priority=70)
    for keyword in REFUELING_MARKERS:
        add("business_route", keyword, target="refueling", action="route", priority=70)
    for keyword in DATA_STRONG_MARKERS:
        add("business_route", keyword, target="data", action="route", priority=70, metadata={"match_type": "strong"})
    for keyword in DATA_CONTEXT_MARKERS:
        add("business_route", keyword, target="data", action="route", priority=60, metadata={"match_type": "context"})
    for keyword in DASHCAM_MARKERS:
        add("business_route", keyword, target="dashcam", action="route", priority=60)

    for keyword in INSTRUCTIONAL_MARKERS:
        add("intent_hint", keyword, target="instructional", action="classify", priority=50)
    for keyword in PERSONAL_QUERY_MARKERS:
        add("intent_hint", keyword, target="personal_query", action="classify", priority=55)

    for pattern, target in QUERY_INTENT_PATTERNS:
        add(
            "query_intent",
            pattern,
            target=target,
            action="regex",
            priority=65,
            metadata={"match_type": "regex"},
            description="实时查询类型识别",
        )

    return rows


async def seed_default_keyword_rules(db) -> int:
    """Insert missing default keyword_rule rows. Existing rows are left intact."""
    from sqlalchemy import select

    from app.models import KeywordRule

    result = await db.execute(
        select(
            KeywordRule.rule_type,
            KeywordRule.keyword,
            KeywordRule.target,
            KeywordRule.business_area,
        )
    )
    existing = {
        (rule_type, keyword, target, business_area)
        for rule_type, keyword, target, business_area in result.all()
    }

    inserted = 0
    for row in get_default_keyword_rule_seed():
        key = (
            row["rule_type"],
            row["keyword"],
            row.get("target"),
            row.get("business_area"),
        )
        if key in existing:
            continue
        db.add(KeywordRule(**row))
        existing.add(key)
        inserted += 1

    if inserted:
        await db.flush()
    return inserted


async def load_keyword_rules(db) -> int:
    """Load active keyword_rule rows into memory once at startup."""
    from sqlalchemy import select

    from app.models import KeywordRule

    result = await db.execute(
        select(KeywordRule)
        .where(KeywordRule.is_active == True)
        .order_by(KeywordRule.priority.desc(), KeywordRule.id.asc())
    )
    rows = list(result.scalars().all())
    return apply_keyword_rule_rows(rows)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("…", "...").replace("。。", "。")
    return re.sub(r"\s+", " ", text)


def extract_vin(text: str) -> Optional[str]:
    if not text:
        return None
    match = re.search(r"[A-HJ-NPR-Z0-9]{17}", text.upper())
    return match.group(0) if match else None


def contains_any(text: str, keywords: Sequence[str]) -> Optional[str]:
    for keyword in keywords:
        if keyword and keyword in text:
            return keyword
    return None


def is_greeting(text: str) -> bool:
    cleaned = normalize_text(text)
    return any(re.match(pattern, cleaned, flags=re.IGNORECASE) for pattern in GREETING_PATTERNS)


def is_transfer_request(text: str) -> bool:
    cleaned = normalize_text(text)
    hit = contains_any(cleaned, _rule_config.transfer_keywords)
    if hit == "人工" and "人工智能" in cleaned:
        return False
    return hit is not None


def detect_business_area(text: str, fallback: str = "dashcam") -> str:
    """Detect business area without letting generic words steal dashcam traffic."""
    t = normalize_text(text).lower()
    fallback = fallback or "dashcam"

    if contains_any(t, _rule_config.wifi_markers):
        return "wifi"
    if contains_any(t, _rule_config.refueling_markers):
        return "refueling"
    if contains_any(t, _rule_config.data_strong_markers):
        return "data"
    if contains_any(t, _rule_config.data_context_markers) and not contains_any(t, _rule_config.dashcam_markers):
        return "data"
    if contains_any(t, _rule_config.dashcam_markers):
        return "dashcam"

    # Generic "充值/续费/套餐" should stay in the current business context.
    return fallback


def evaluate_transfer(text: str, business_area: str = "dashcam") -> TransferDecision:
    """Decide whether to hand off before retrieval.

    Plain "怎么退款" is allowed to reach the relevant knowledge base.  It becomes
    risk only when it carries complaint/dispute language.
    """
    t = normalize_text(text)

    hit = contains_any(t, _rule_config.transfer_keywords)
    if hit == "人工" and "人工智能" in t:
        hit = None
    if hit:
        return TransferDecision(True, "user_request", "用户要求转人工", "normal", hit)

    hit = contains_any(t, _rule_config.unsupported_operations)
    if hit:
        return TransferDecision(True, "out_of_scope", f"超出AI服务范围: {hit}", "normal", hit)

    hit = contains_any(t, _rule_config.high_risk_keywords)
    if hit:
        return TransferDecision(True, "risk", f"检测到高风险关键词: {hit}", "high", hit)

    if "退款" in t and not (
        business_area == "refueling"
        and contains_any(t, ("怎么", "如何", "流程", "规则", "可以", "能不能", "是否"))
    ):
        return TransferDecision(True, "risk", "检测到退款诉求", "high", "退款")

    refund_hit = contains_any(t, _rule_config.refund_risk_markers)
    if refund_hit:
        return TransferDecision(True, "risk", f"检测到退款争议关键词: {refund_hit}", "high", refund_hit)

    return TransferDecision(False)


def should_route_live_query(text: str, query_type_code: Optional[str]) -> bool:
    """Split personal data lookup from tutorial/rule knowledge questions."""
    if not query_type_code:
        return False
    if extract_vin(text):
        return True

    t = normalize_text(text).lower()
    if contains_any(t, _rule_config.personal_query_markers):
        return True
    if contains_any(t, _rule_config.instructional_markers):
        return False
    if query_type_code == "QRY009":
        return False
    return False


def match_query_type(text: str) -> Optional[str]:
    t = normalize_text(text).lower()
    for rule in _rule_config.query_intent_rules:
        if not rule.keyword or not rule.target:
            continue
        if rule.is_regex:
            try:
                if re.search(rule.keyword, t):
                    return rule.target
            except re.error:
                continue
        elif rule.keyword.lower() in t:
            return rule.target
    return _fallback_match_query_type(text)


def classify_intent(text: str, fallback_business: str = "dashcam") -> IntentDecision:
    cleaned = normalize_text(text)
    business_area = detect_business_area(cleaned, fallback_business)

    if is_greeting(cleaned):
        return IntentDecision("greeting", 0.95, business_area, method="rule:greeting")
    if is_transfer_request(cleaned):
        return IntentDecision("transfer_request", 0.99, business_area, method="rule:transfer")

    query_type_code = match_query_type(cleaned)
    if business_area == "dashcam" and should_route_live_query(cleaned, query_type_code):
        return IntentDecision("live_query", 0.9, business_area, query_type_code, method="rule:live_query")

    return IntentDecision("knowledge_query", 0.75, business_area, query_type_code, method="rule:knowledge")


def needs_clarify(query: str, scores: Sequence[float], method: str) -> bool:
    q = normalize_text(query)
    if contains_any(q, ("怎么", "如何", "什么", "为什么", "哪", "吗", "呢")):
        return False
    if len(q) < 5:
        return True
    if (
        method == "vector_low"
        and len(scores) >= 2
        and scores[0] < 0.65
        and (scores[0] - scores[1]) < 0.05
    ):
        return True
    return False
