# 转人工决策单元测试

import pytest
from app.nodes.human_transfer import (
    HIGH_RISK_KEYWORDS,
    UNSUPPORTED_OPERATIONS,
    _evaluate_transfer,
    _is_off_hours,
)
from app.nodes.preprocess import check_transfer_keyword
import json
from pathlib import Path

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sample_queries.json"
SAMPLES = json.loads(FIXTURES.read_text(encoding="utf-8"))


def test_high_risk_keywords():
    """测试高风险关键词检测"""
    for sample in SAMPLES["high_risk"]:
        state = {"query": sample["query"], "consecutive_fail_count": 0, "intent_type": "unknown"}
        should, reason_type, reason = _evaluate_transfer(state)
        assert should, f"应触发转人工: {sample['query']}"
        assert reason_type == sample["reason_type"], f"{sample['query']} → {reason_type}"


def test_consecutive_fail_transfer():
    """测试连续失败转人工"""
    state = {"query": "设备问题", "consecutive_fail_count": 3, "intent_type": "knowledge_query"}
    should, reason_type, reason = _evaluate_transfer(state)
    assert should
    assert reason_type == "consecutive_fail"


def test_out_of_scope():
    """测试超出范围操作"""
    for op in ["修改绑定", "解绑", "激活设备", "修改套餐"]:
        state = {"query": f"帮我{op}", "consecutive_fail_count": 0, "intent_type": "unknown"}
        should, reason_type, reason = _evaluate_transfer(state)
        assert should, f"应触发转人工: {op}"
        assert reason_type == "out_of_scope"


def test_no_transfer_normal():
    """测试正常情况不转人工"""
    state = {"query": "设备怎么重启", "consecutive_fail_count": 0, "intent_type": "knowledge_query"}
    should, _, _ = _evaluate_transfer(state)
    assert not should


def test_off_hours():
    """测试非工作时间判断 (仅验证函数可调用)"""
    result = _is_off_hours()
    assert isinstance(result, bool)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
