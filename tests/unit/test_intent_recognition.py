# 意图识别单元测试

import pytest
import asyncio
import json
from pathlib import Path

# 加载测试用例
FIXTURES = Path(__file__).parent.parent / "fixtures" / "sample_queries.json"
SAMPLES = json.loads(FIXTURES.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_transfer_keyword_detection():
    """测试转人工关键词检测"""
    from app.nodes.preprocess import check_transfer_keyword

    for sample in SAMPLES["transfer_requests"]:
        assert check_transfer_keyword(sample["query"]), f"应检测到转人工: {sample['query']}"

    # 不应误判
    assert not check_transfer_keyword("设备离线怎么办")
    assert not check_transfer_keyword("怎么查询SIM卡号")


@pytest.mark.asyncio
async def test_greeting_detection():
    """测试问候语检测"""
    from app.nodes.preprocess import check_greeting

    for sample in SAMPLES["greetings"]:
        assert check_greeting(sample["query"]), f"应检测到问候: {sample['query']}"

    assert not check_greeting("设备怎么重启")


@pytest.mark.asyncio
async def test_mock_llm_classify():
    """测试 Mock LLM 意图分类"""
    from app.services.llm_service import MockProvider

    llm = MockProvider()

    # 转人工
    result = await llm.classify("我要转人工", ["knowledge_query", "live_query", "transfer_request", "greeting", "unknown"])
    assert result["label"] == "transfer_request"

    # 问候
    result = await llm.classify("你好", ["knowledge_query", "live_query", "transfer_request", "greeting", "unknown"])
    assert result["label"] == "greeting"

    # 查询
    result = await llm.classify("帮我查一下SIM卡号", ["knowledge_query", "live_query", "transfer_request", "greeting", "unknown"])
    assert result["label"] == "live_query"


@pytest.mark.asyncio
async def test_query_type_matching():
    """测试查询类型匹配"""
    from app.nodes.query_judgment import _match_query_type

    for sample in SAMPLES["live_queries"]:
        qtype = _match_query_type(sample["query"])
        assert qtype is not None, f"应匹配查询类型: {sample['query']}"
        if "expected_query_type" in sample:
            assert qtype == sample["expected_query_type"], f"{sample['query']} → {qtype} != {sample['expected_query_type']}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
