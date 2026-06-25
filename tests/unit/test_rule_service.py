import pytest

from app.services.brand_service import BrandIdentificationService
from app.services.rule_service import (
    apply_keyword_rule_rows,
    classify_intent,
    detect_business_area,
    evaluate_transfer,
    get_default_keyword_rule_seed,
    match_query_type,
    reset_keyword_rules,
)


def test_business_area_keeps_generic_renewal_in_dashcam_context():
    assert detect_business_area("设备怎么续费", "dashcam") == "dashcam"
    assert detect_business_area("行车记录仪怎么续费", "dashcam") == "dashcam"


def test_business_area_routes_specific_business_knowledge():
    assert detect_business_area("WiFi套餐怎么续费", "dashcam") == "wifi"
    assert detect_business_area("基础流量充值不到账怎么办", "dashcam") == "data"
    assert detect_business_area("加油券怎么退款", "dashcam") == "refueling"


def test_transfer_rules_do_not_block_refueling_refund_how_to_question():
    decision = evaluate_transfer("加油券怎么退款", "refueling")
    assert not decision.should_transfer

    decision = evaluate_transfer("退款", "refueling")
    assert decision.should_transfer
    assert decision.reason_type == "risk"


def test_intent_splits_live_query_from_knowledge_question():
    assert classify_intent("怎么查询SIM卡号", "dashcam").intent_type == "knowledge_query"
    assert classify_intent("设备怎么续费", "dashcam").intent_type == "knowledge_query"

    live = classify_intent("我的设备状态怎么样", "dashcam")
    assert live.intent_type == "live_query"
    assert live.query_type_code == "QRY010"

    live = classify_intent("帮我查一下SIM卡号是多少", "dashcam")
    assert live.intent_type == "live_query"
    assert live.query_type_code == "QRY001"


def test_default_keyword_rule_seed_contains_core_rule_groups():
    rows = get_default_keyword_rule_seed()

    assert any(r["rule_type"] == "transfer" and r["keyword"] == "转人工" for r in rows)
    assert any(r["rule_type"] == "business_route" and r["target"] == "wifi" for r in rows)
    assert any(r["rule_type"] == "query_intent" and r["target"] == "QRY001" for r in rows)
    assert all("extra_metadata" in r for r in rows)


def test_keyword_rule_rows_override_configured_group_and_keep_fallbacks():
    try:
        apply_keyword_rule_rows([
            {
                "rule_type": "business_route",
                "keyword": "专属wifi",
                "target": "wifi",
                "extra_metadata": {},
            },
            {
                "rule_type": "intent_hint",
                "keyword": "帮忙查",
                "target": "personal_query",
                "extra_metadata": {},
            },
            {
                "rule_type": "query_intent",
                "keyword": "专属编号",
                "target": "QRY002",
                "action": "contains",
                "extra_metadata": {},
            },
        ])

        assert detect_business_area("专属wifi打不开", "dashcam") == "wifi"
        assert detect_business_area("加油券怎么退款", "dashcam") == "refueling"
        assert match_query_type("请看一下专属编号") == "QRY002"
    finally:
        reset_keyword_rules()


@pytest.mark.asyncio
async def test_brand_keyword_prefers_longer_alias_and_keeps_yukuai_ambiguous():
    service = BrandIdentificationService()

    result = await service.identify_by_keyword("极目单北斗设备离线")
    assert result.brand_name == "极目单北斗(DBD)"

    result = await service.identify_by_keyword("鱼快设备厂家代码是多少")
    assert result.brand_name is None
    assert result.confidence < 0.8
