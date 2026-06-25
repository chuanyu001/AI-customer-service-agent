import asyncio
import json

import pytest

from app.core.config import settings
from app.services.llm_service import MockProvider, set_llm
from app.services.llm_understanding_service import (
    fallback_understanding,
    llm_understanding_service,
    parse_understanding_response,
)


class StaticLLM:
    def __init__(self, response: str):
        self.response = response
        self.calls = 0
        self.messages = []

    async def chat(self, messages, **kwargs):
        self.calls += 1
        self.messages.append(messages)
        return self.response


class SlowLLM:
    async def chat(self, messages, **kwargs):
        await asyncio.sleep(0.2)
        return "{}"


def teardown_function():
    set_llm(MockProvider())


def test_parse_llm_understanding_success():
    response = json.dumps({
        "intent_type": "live_query",
        "business_area": "dashcam",
        "query_type_code": "QRY007",
        "rewritten_query": "我的车 LFNAHUPMXT1E19383 服务什么时候到期",
        "slots": {"vin": "LFNAHUPMXT1E19383"},
        "confidence": 0.91,
        "need_clarify": False,
        "clarify_question": "",
    }, ensure_ascii=False)

    result = parse_understanding_response(response, "这个什么时候到期", "dashcam")

    assert result.intent_type == "live_query"
    assert result.business_area == "dashcam"
    assert result.query_type_code == "QRY007"
    assert result.rewritten_query == "我的车 LFNAHUPMXT1E19383 服务什么时候到期"
    assert result.slots["vin"] == "LFNAHUPMXT1E19383"
    assert result.confidence == 0.91
    assert not result.fallback_used


def test_parse_llm_understanding_missing_fields_uses_defaults():
    result = parse_understanding_response("{}", "WiFi怎么开通", "dashcam")

    assert result.intent_type == "knowledge_query"
    assert result.business_area == "wifi"
    assert result.rewritten_query == "WiFi怎么开通"
    assert result.confidence == 0.6


def test_parse_llm_understanding_invalid_json_falls_back_to_rules():
    result = parse_understanding_response("not json", "我要查一下SIM卡号是多少", "dashcam")

    assert result.fallback_used
    assert result.method == "rule_fallback"
    assert result.intent_type == "live_query"
    assert result.query_type_code == "QRY001"


def test_rule_fallback_extracts_vin_slot():
    result = fallback_understanding("我的车 LFNAHUPMXT1E19383 到期了吗", "dashcam")

    assert result.fallback_used
    assert result.intent_type == "live_query"
    assert result.slots["vin"] == "LFNAHUPMXT1E19383"


@pytest.mark.asyncio
async def test_llm_understanding_rewrites_with_history():
    llm = StaticLLM(json.dumps({
        "intent_type": "knowledge_query",
        "business_area": "wifi",
        "query_type_code": "QRY007",
        "rewritten_query": "WiFi套餐怎么续费",
        "slots": {},
        "confidence": 0.88,
        "need_clarify": False,
        "clarify_question": "",
    }, ensure_ascii=False))
    set_llm(llm)

    result = await llm_understanding_service.understand(
        "那怎么续费",
        business_area="wifi",
        history=[
            {"role": "user", "content": "WiFi怎么开通"},
            {"role": "assistant", "content": "这是WiFi开通说明"},
        ],
        memory={"summary": "用户咨询WiFi开通", "slots": {}},
    )

    assert result.intent_type == "knowledge_query"
    assert result.business_area == "wifi"
    assert result.rewritten_query == "WiFi套餐怎么续费"
    assert llm.calls == 1
    assert "recent_messages" in llm.messages[0][1]["content"]


@pytest.mark.asyncio
async def test_llm_understanding_timeout_uses_rule_fallback(monkeypatch):
    set_llm(SlowLLM())
    monkeypatch.setattr(settings, "LLM_UNDERSTANDING_TIMEOUT", 0.01)

    result = await llm_understanding_service.understand(
        "怎么查询SIM卡号",
        business_area="dashcam",
    )

    assert result.fallback_used
    assert result.method == "rule_fallback"
    assert result.intent_type == "knowledge_query"
