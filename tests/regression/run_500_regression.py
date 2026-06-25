"""Run 500 deterministic regression cases for the current chat strategy.

The suite covers rule routing, intent split, handoff rules, brand recognition,
database cleanup invariants, exact retrieval for every published knowledge row,
and semantic retrieval for representative paraphrases.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Optional


os.environ.setdefault("DEBUG", "false")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from sqlalchemy import func, select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import close_db, get_session_factory  # noqa: E402
from app.models import BUSINESS_KNOWLEDGE_MAP, BrandInfo  # noqa: E402
from app.services.brand_service import BrandIdentificationService  # noqa: E402
from app.services.embedding_service import embedding_service  # noqa: E402
from app.services.knowledge_service import knowledge_service  # noqa: E402
from app.services.llm_service import MockProvider, set_llm  # noqa: E402
from app.services.llm_understanding_service import llm_understanding_service  # noqa: E402
from app.services.rule_service import (  # noqa: E402
    classify_intent,
    detect_business_area,
    evaluate_transfer,
    extract_vin,
    is_greeting,
    is_transfer_request,
    needs_clarify,
)


@dataclass(frozen=True)
class CaseResult:
    group: str
    name: str
    passed: bool
    detail: str = ""


def check_equal(group: str, name: str, actual, expected) -> CaseResult:
    ok = actual == expected
    detail = "" if ok else f"expected={expected!r}, actual={actual!r}"
    return CaseResult(group, name, ok, detail)


def check_true(group: str, name: str, condition: bool, detail: str = "") -> CaseResult:
    return CaseResult(group, name, bool(condition), "" if condition else detail)


def run_business_cases() -> list[CaseResult]:
    cases = [
        # dashcam
        ("设备怎么续费", "dashcam", "dashcam"),
        ("行车记录仪怎么开通", "wifi", "dashcam"),
        ("终端状态怎么看", "data", "dashcam"),
        ("北斗设备离线怎么办", "refueling", "dashcam"),
        ("车架号怎么查设备", "wifi", "dashcam"),
        ("SIM卡怎么拔插", "data", "dashcam"),
        ("怎么查询SIM卡号", "refueling", "dashcam"),
        ("记录仪设备怎么重启", "wifi", "dashcam"),
        ("终端号在哪里看", "data", "dashcam"),
        ("设备密码是多少", "refueling", "dashcam"),
        ("设备如何安装", "wifi", "dashcam"),
        ("车辆设备怎么激活", "data", "dashcam"),
        ("北斗终端怎么查询", "refueling", "dashcam"),
        ("SIM卡号在哪里", "wifi", "dashcam"),
        ("车架号绑定设备怎么查", "data", "dashcam"),
        ("终端离线怎么处理", "refueling", "dashcam"),
        ("记录仪视频怎么导出", "wifi", "dashcam"),
        ("行车记录仪厂家怎么判断", "data", "dashcam"),
        ("设备到期怎么续费", "refueling", "dashcam"),
        ("北斗状态异常怎么办", "wifi", "dashcam"),
        # wifi
        ("WiFi套餐怎么续费", "dashcam", "wifi"),
        ("怎么开通WiFi", "dashcam", "wifi"),
        ("车内wifi无法连接", "dashcam", "wifi"),
        ("热点密码在哪里", "dashcam", "wifi"),
        ("无线网络怎么改密码", "dashcam", "wifi"),
        ("随车wifi怎么购买", "dashcam", "wifi"),
        ("Wi-Fi连不上怎么办", "dashcam", "wifi"),
        ("WiFi发票怎么开", "dashcam", "wifi"),
        ("车机热点怎么打开", "dashcam", "wifi"),
        ("无线网套餐在哪里看", "dashcam", "wifi"),
        ("WiFi充值不到账怎么办", "dashcam", "wifi"),
        ("热点流量怎么查询", "dashcam", "wifi"),
        ("随车wifi服务到期", "dashcam", "wifi"),
        ("WiFi账号在哪里", "dashcam", "wifi"),
        ("车内无线网络怎么续费", "dashcam", "wifi"),
        ("热点连接失败", "dashcam", "wifi"),
        ("Wi-Fi密码忘了", "dashcam", "wifi"),
        ("随车无线网开通流程", "dashcam", "wifi"),
        ("WiFi设备怎么绑定", "dashcam", "wifi"),
        ("热点套餐什么时候生效", "dashcam", "wifi"),
        # data
        ("基础流量充值不到账怎么办", "dashcam", "data"),
        ("流量包怎么购买", "dashcam", "data"),
        ("流量套餐什么时候生效", "dashcam", "data"),
        ("流量卡怎么续费", "dashcam", "data"),
        ("青岛流量怎么充值", "dashcam", "data"),
        ("长春流量到期了怎么办", "dashcam", "data"),
        ("流量怎么开发票", "dashcam", "data"),
        ("基础流量在哪里查询", "dashcam", "data"),
        ("流量充值失败怎么办", "dashcam", "data"),
        ("流量包发票怎么开", "dashcam", "data"),
        ("流量套餐怎么退订", "dashcam", "data"),
        ("基地月包怎么开通", "dashcam", "data"),
        ("流量卡余额怎么查", "dashcam", "data"),
        ("青岛流量包不到账", "dashcam", "data"),
        ("长春流量套餐发票", "dashcam", "data"),
        ("基础流量到期提醒", "dashcam", "data"),
        ("流量充值入口在哪里", "dashcam", "data"),
        ("流量包能不能续费", "dashcam", "data"),
        ("流量套餐查询方式", "dashcam", "data"),
        ("流量卡开通流程", "dashcam", "data"),
        # refueling
        ("加油券怎么退款", "dashcam", "refueling"),
        ("加油怎么开发票", "dashcam", "refueling"),
        ("油价在哪里看", "dashcam", "refueling"),
        ("柴油能不能用油券", "dashcam", "refueling"),
        ("加油订单怎么查询", "dashcam", "refueling"),
        ("油站优惠在哪里看", "dashcam", "refueling"),
        ("油卡充值失败怎么办", "dashcam", "refueling"),
        ("汽油券怎么使用", "dashcam", "refueling"),
        ("燃油发票怎么开", "dashcam", "refueling"),
        ("加油券有效期多久", "dashcam", "refueling"),
        ("油站列表在哪里", "dashcam", "refueling"),
        ("柴油车能用加油券吗", "dashcam", "refueling"),
        ("加油支付失败怎么办", "dashcam", "refueling"),
        ("油券余额怎么查", "dashcam", "refueling"),
        ("加油订单退款规则", "dashcam", "refueling"),
        ("油卡发票开具流程", "dashcam", "refueling"),
        ("汽油优惠券怎么购买", "dashcam", "refueling"),
        ("燃油券不到账怎么办", "dashcam", "refueling"),
        ("加油站在哪里看", "dashcam", "refueling"),
        ("油价优惠活动怎么参加", "dashcam", "refueling"),
    ]
    return [check_equal("business", query, detect_business_area(query, fallback), expected) for query, fallback, expected in cases[:70]]


class StaticLLM:
    def __init__(self, response: str):
        self.response = response

    async def chat(self, messages, **kwargs):
        return self.response


async def run_llm_understanding_cases() -> list[CaseResult]:
    import json

    scenarios = [
        (
            "wifi context rewrite",
            "那怎么续费",
            "wifi",
            [{"role": "user", "content": "WiFi怎么开通"}],
            {
                "intent_type": "knowledge_query",
                "business_area": "wifi",
                "query_type_code": "QRY007",
                "rewritten_query": "WiFi套餐怎么续费",
                "slots": {},
                "confidence": 0.9,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "wifi", "QRY007", "WiFi套餐怎么续费", False),
        ),
        (
            "live query vin",
            "这个什么时候到期",
            "dashcam",
            [{"role": "user", "content": "LFNAHUPMXT1E19383"}],
            {
                "intent_type": "live_query",
                "business_area": "dashcam",
                "query_type_code": "QRY007",
                "rewritten_query": "我的车 LFNAHUPMXT1E19383 服务什么时候到期",
                "slots": {"vin": "LFNAHUPMXT1E19383"},
                "confidence": 0.92,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("live_query", "dashcam", "QRY007", "我的车 LFNAHUPMXT1E19383 服务什么时候到期", False),
        ),
        (
            "clarify",
            "这个怎么弄",
            "dashcam",
            [],
            {
                "intent_type": "clarify",
                "business_area": "dashcam",
                "query_type_code": None,
                "rewritten_query": "这个怎么弄",
                "slots": {},
                "confidence": 0.45,
                "need_clarify": True,
                "clarify_question": "请说明您指的是哪个设备或服务。",
            },
            ("clarify", "dashcam", None, "这个怎么弄", True),
        ),
        (
            "transfer",
            "还是帮我找人工吧",
            "dashcam",
            [],
            {
                "intent_type": "transfer_request",
                "business_area": "dashcam",
                "query_type_code": None,
                "rewritten_query": "用户要求转人工客服",
                "slots": {},
                "confidence": 0.95,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("transfer_request", "dashcam", None, "用户要求转人工客服", False),
        ),
        (
            "data route",
            "这个套餐怎么查",
            "data",
            [{"role": "user", "content": "基础流量怎么充值"}],
            {
                "intent_type": "knowledge_query",
                "business_area": "data",
                "query_type_code": "QRY013",
                "rewritten_query": "基础流量套餐怎么查询",
                "slots": {},
                "confidence": 0.86,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "data", "QRY013", "基础流量套餐怎么查询", False),
        ),
        (
            "brand slot",
            "雅迅",
            "dashcam",
            [{"role": "assistant", "content": "请告知设备品牌"}],
            {
                "intent_type": "knowledge_query",
                "business_area": "dashcam",
                "query_type_code": None,
                "rewritten_query": "用户设备品牌为雅迅",
                "slots": {"brand_name": "雅迅"},
                "confidence": 0.88,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "dashcam", "QRY011", "用户设备品牌为雅迅", False),
        ),
        (
            "refueling",
            "那发票呢",
            "refueling",
            [{"role": "user", "content": "加油券怎么用"}],
            {
                "intent_type": "knowledge_query",
                "business_area": "refueling",
                "query_type_code": None,
                "rewritten_query": "加油订单如何开发票",
                "slots": {},
                "confidence": 0.82,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "refueling", None, "加油订单如何开发票", False),
        ),
        (
            "wifi status",
            "这个连不上",
            "wifi",
            [{"role": "user", "content": "车内WiFi"}],
            {
                "intent_type": "knowledge_query",
                "business_area": "wifi",
                "query_type_code": None,
                "rewritten_query": "车内WiFi连不上怎么办",
                "slots": {},
                "confidence": 0.84,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "wifi", None, "车内WiFi连不上怎么办", False),
        ),
        (
            "unknown qtype inferred",
            "怎么查询终端编号",
            "dashcam",
            [],
            {
                "intent_type": "knowledge_query",
                "business_area": "dashcam",
                "query_type_code": None,
                "rewritten_query": "怎么查询终端编号",
                "slots": {},
                "confidence": 0.77,
                "need_clarify": False,
                "clarify_question": "",
            },
            ("knowledge_query", "dashcam", "QRY002", "怎么查询终端编号", False),
        ),
    ]

    results: list[CaseResult] = []
    for name, query, area, history, payload, expected in scenarios:
        set_llm(StaticLLM(json.dumps(payload, ensure_ascii=False)))
        result = await llm_understanding_service.understand(query, business_area=area, history=history)
        expected_intent, expected_area, expected_qtype, expected_rewrite, expected_clarify = expected
        ok = (
            result.intent_type == expected_intent
            and result.business_area == expected_area
            and result.query_type_code == expected_qtype
            and result.rewritten_query == expected_rewrite
            and result.need_clarify == expected_clarify
            and not result.fallback_used
        )
        detail = (
            f"actual intent={result.intent_type}, area={result.business_area}, "
            f"qtype={result.query_type_code}, rewrite={result.rewritten_query}, "
            f"clarify={result.need_clarify}, fallback={result.fallback_used}"
        )
        results.append(check_true("llm_understanding", name, ok, detail))

    set_llm(StaticLLM("not-json"))
    fallback = await llm_understanding_service.understand("帮我查一下SIM卡号是多少", business_area="dashcam")
    results.append(check_true(
        "llm_understanding",
        "invalid json fallback",
        fallback.fallback_used and fallback.intent_type == "live_query" and fallback.query_type_code == "QRY001",
        f"actual={fallback}",
    ))
    set_llm(MockProvider())
    return results


def run_intent_cases() -> list[CaseResult]:
    cases: list[tuple[str, str, str, str, Optional[str]]] = []
    query_targets = [
        ("SIM卡号", "QRY001"),
        ("ICCID", "QRY001"),
        ("终端号", "QRY002"),
        ("设备号", "QRY002"),
        ("服务商", "QRY004"),
        ("运营商", "QRY004"),
        ("司机卡", "QRY005"),
        ("车辆信息", "QRY006"),
        ("车主信息", "QRY006"),
        ("续费", "QRY007"),
        ("服务到期", "QRY007"),
        ("设备在线状态", "QRY010"),
        ("设备离线状态", "QRY010"),
        ("设备品牌", "QRY011"),
        ("设备型号", "QRY012"),
        ("流量套餐", "QRY013"),
        ("流量卡", "QRY013"),
        ("缴费开通", "QRY009"),
        ("激活流程", "QRY009"),
        ("终端SIM关系", "QRY001"),
    ]
    knowledge_prefixes = ["怎么查询", "如何查看"]
    for idx, (target, qtype) in enumerate(query_targets):
        expected_area = "data" if "流量" in target else "dashcam"
        cases.append((f"{knowledge_prefixes[idx % 2]}{target}", "dashcam", "knowledge_query", expected_area, qtype))

    live_prefixes = ["帮我查一下我的", "我的", "这台车的", "帮我查询"]
    for idx, (target, qtype) in enumerate(query_targets[:25] + query_targets[:5]):
        expected_area = "data" if "流量" in target else "dashcam"
        expected_intent = "knowledge_query" if expected_area != "dashcam" else "live_query"
        cases.append((f"{live_prefixes[idx % 4]}{target}是多少", "dashcam", expected_intent, expected_area, qtype))

    business_queries = [
        ("怎么开通WiFi", "dashcam", "knowledge_query", "wifi", "QRY009"),
        ("WiFi套餐怎么续费", "dashcam", "knowledge_query", "wifi", "QRY007"),
        ("车内WiFi连不上怎么办", "dashcam", "knowledge_query", "wifi", None),
        ("热点密码在哪里", "dashcam", "knowledge_query", "wifi", None),
        ("随车wifi怎么购买", "dashcam", "knowledge_query", "wifi", None),
        ("WiFi发票怎么开", "dashcam", "knowledge_query", "wifi", None),
        ("无线网络怎么改密码", "dashcam", "knowledge_query", "wifi", None),
        ("基础流量怎么充值", "dashcam", "knowledge_query", "data", None),
        ("流量卡套餐怎么查询", "dashcam", "knowledge_query", "data", "QRY013"),
        ("流量充值不到账怎么办", "dashcam", "knowledge_query", "data", None),
        ("青岛流量怎么充值", "dashcam", "knowledge_query", "data", None),
        ("长春流量到期怎么办", "dashcam", "knowledge_query", "data", "QRY007"),
        ("流量怎么开发票", "dashcam", "knowledge_query", "data", "QRY013"),
        ("流量包怎么购买", "dashcam", "knowledge_query", "data", "QRY013"),
        ("加油券怎么退款", "dashcam", "knowledge_query", "refueling", None),
        ("加油订单如何开发票", "dashcam", "knowledge_query", "refueling", None),
        ("油价在哪里看", "dashcam", "knowledge_query", "refueling", None),
        ("柴油能不能用油券", "dashcam", "knowledge_query", "refueling", None),
        ("加油站在哪里看", "dashcam", "knowledge_query", "refueling", None),
        ("油卡充值失败怎么办", "dashcam", "knowledge_query", "refueling", None),
        ("加油券有效期多久", "dashcam", "knowledge_query", "refueling", None),
        ("设备怎么重启", "dashcam", "knowledge_query", "dashcam", None),
        ("怎么查询SIM卡号", "dashcam", "knowledge_query", "dashcam", "QRY001"),
        ("SIM卡怎么拔插", "dashcam", "knowledge_query", "dashcam", "QRY001"),
        ("设备密码是多少", "dashcam", "knowledge_query", "dashcam", None),
        ("我的车架号是LFNAHUPMXT1E19383，查一下设备号", "dashcam", "live_query", "dashcam", "QRY002"),
        ("LFNAHUPMXT1E19383 查询服务商", "dashcam", "live_query", "dashcam", "QRY004"),
        ("人工客服", "dashcam", "transfer_request", "dashcam", None),
        ("我要转人工", "dashcam", "transfer_request", "dashcam", None),
        ("你好", "dashcam", "greeting", "dashcam", None),
        ("hello", "dashcam", "greeting", "dashcam", None),
        ("套餐怎么续费", "wifi", "knowledge_query", "wifi", "QRY007"),
        ("套餐怎么续费", "data", "knowledge_query", "data", "QRY007"),
        ("套餐怎么续费", "refueling", "knowledge_query", "refueling", "QRY007"),
        ("设备状态怎么样", "dashcam", "live_query", "dashcam", "QRY010"),
        ("我的设备状态怎么样", "dashcam", "live_query", "dashcam", "QRY010"),
        ("我的服务什么时候到期", "dashcam", "live_query", "dashcam", "QRY007"),
        ("怎么查看设备在线状态", "dashcam", "knowledge_query", "dashcam", "QRY010"),
        ("ICCID怎么查询", "dashcam", "knowledge_query", "dashcam", "QRY001"),
        ("帮我查ICCID是多少", "dashcam", "live_query", "dashcam", "QRY001"),
        ("我的设备哪个服务商", "dashcam", "live_query", "dashcam", "QRY004"),
        ("怎么查询设备品牌", "dashcam", "knowledge_query", "dashcam", "QRY011"),
        ("怎么查询设备型号", "dashcam", "knowledge_query", "dashcam", "QRY012"),
        ("怎么缴费开通", "dashcam", "knowledge_query", "dashcam", "QRY009"),
        ("车辆信息怎么查", "dashcam", "knowledge_query", "dashcam", "QRY006"),
        ("司机卡怎么查", "dashcam", "knowledge_query", "dashcam", "QRY005"),
        ("设备服务商怎么查", "dashcam", "knowledge_query", "dashcam", "QRY004"),
        ("设备离线了吗", "dashcam", "live_query", "dashcam", "QRY010"),
        ("这台设备离线了吗", "dashcam", "live_query", "dashcam", "QRY010"),
        ("怎么查询设备号", "dashcam", "knowledge_query", "dashcam", "QRY002"),
        ("WiFi状态怎么查", "dashcam", "knowledge_query", "wifi", "QRY010"),
        ("流量套餐发票怎么开", "dashcam", "knowledge_query", "data", "QRY013"),
        ("加油发票怎么开", "dashcam", "knowledge_query", "refueling", None),
        ("设备套餐怎么续费", "dashcam", "knowledge_query", "dashcam", "QRY007"),
        ("我的车架号LFNAHUPMXT1E19383设备状态", "dashcam", "live_query", "dashcam", "QRY010"),
    ]
    cases.extend(business_queries)

    results: list[CaseResult] = []
    for query, fallback, expected_intent, expected_area, expected_qtype in cases:
        decision = classify_intent(query, fallback)
        ok = (
            decision.intent_type == expected_intent
            and decision.business_area == expected_area
            and (expected_qtype is None or decision.query_type_code == expected_qtype)
        )
        detail = (
            f"expected intent={expected_intent}, area={expected_area}, qtype={expected_qtype}; "
            f"actual intent={decision.intent_type}, area={decision.business_area}, qtype={decision.query_type_code}"
        )
        results.append(check_true("intent", query, ok, detail))
    return results[:100]


def run_transfer_cases() -> list[CaseResult]:
    cases = [
        ("我要转人工", "dashcam", True, "user_request"),
        ("找人工客服", "dashcam", True, "user_request"),
        ("真人服务", "dashcam", True, "user_request"),
        ("转接人工电话", "dashcam", True, "user_request"),
        ("人工客服在吗", "dashcam", True, "user_request"),
        ("请转人工服务", "dashcam", True, "user_request"),
        ("我要找客服", "dashcam", True, "user_request"),
        ("帮我转接", "dashcam", True, "user_request"),
        ("需要真人处理", "dashcam", True, "user_request"),
        ("给我人工电话", "dashcam", True, "user_request"),
        ("人工服务在哪里", "dashcam", True, "user_request"),
        ("转人工处理", "dashcam", True, "user_request"),
        ("我要投诉", "dashcam", True, "risk"),
        ("我要打12315", "dashcam", True, "risk"),
        ("315投诉", "dashcam", True, "risk"),
        ("我要起诉你们", "dashcam", True, "risk"),
        ("媒体曝光你们", "dashcam", True, "risk"),
        ("欺诈骗人", "dashcam", True, "risk"),
        ("我要赔偿", "dashcam", True, "risk"),
        ("我要维权", "dashcam", True, "risk"),
        ("找消协投诉", "dashcam", True, "risk"),
        ("工商投诉", "dashcam", True, "risk"),
        ("退款", "dashcam", True, "risk"),
        ("我要退款", "wifi", True, "risk"),
        ("要求退款", "data", True, "risk"),
        ("不给退", "refueling", True, "risk"),
        ("不退钱", "refueling", True, "risk"),
        ("乱扣费", "refueling", True, "risk"),
        ("恶意扣费", "refueling", True, "risk"),
        ("退款投诉", "refueling", True, "risk"),
        ("帮我解绑设备", "dashcam", True, "out_of_scope"),
        ("帮我修改绑定", "dashcam", True, "out_of_scope"),
        ("帮我换绑设备", "dashcam", True, "out_of_scope"),
        ("帮我激活设备", "dashcam", True, "out_of_scope"),
        ("修改套餐", "dashcam", True, "out_of_scope"),
        ("修改缴费记录", "dashcam", True, "out_of_scope"),
        ("写车架号", "dashcam", True, "out_of_scope"),
        ("下发车架号", "dashcam", True, "out_of_scope"),
        ("车辆信息写入", "dashcam", True, "out_of_scope"),
        ("入网审核", "dashcam", True, "out_of_scope"),
        ("开通审核", "dashcam", True, "out_of_scope"),
        ("修改设备资料", "dashcam", True, "out_of_scope"),
        ("加油券怎么退款", "refueling", False, ""),
        ("加油券退款流程是什么", "refueling", False, ""),
        ("加油券能不能退款", "refueling", False, ""),
        ("怎么退款", "refueling", False, ""),
        ("如何退款", "refueling", False, ""),
        ("退款规则是什么", "refueling", False, ""),
        ("客服在吗", "dashcam", False, ""),
        ("人工智能客服是什么", "dashcam", False, ""),
        ("设备怎么重启", "dashcam", False, ""),
        ("设备续费流程", "dashcam", False, ""),
        ("WiFi怎么开通", "wifi", False, ""),
        ("流量包怎么购买", "data", False, ""),
        ("加油怎么开发票", "refueling", False, ""),
        ("SIM卡怎么查询", "dashcam", False, ""),
        ("设备离线怎么办", "dashcam", False, ""),
        ("油价在哪里看", "refueling", False, ""),
        ("热点连不上怎么办", "wifi", False, ""),
        ("基础流量充值不到账怎么办", "data", False, ""),
    ]
    results = []
    for query, area, expected_transfer, expected_reason in cases:
        decision = evaluate_transfer(query, area)
        ok = decision.should_transfer == expected_transfer and (
            not expected_reason or decision.reason_type == expected_reason
        )
        detail = (
            f"expected transfer={expected_transfer}, reason={expected_reason}; "
            f"actual transfer={decision.should_transfer}, reason={decision.reason_type}, detail={decision.reason}"
        )
        results.append(check_true("transfer", query, ok, detail))
    return results


def run_utility_cases() -> list[CaseResult]:
    cases = [
        check_true("utility", "greeting:你好", is_greeting("你好")),
        check_true("utility", "greeting:您好", is_greeting("您好")),
        check_true("utility", "greeting:hello", is_greeting("hello")),
        check_true("utility", "greeting:在吗", is_greeting("在吗")),
        check_true("utility", "not greeting", not is_greeting("设备怎么续费")),
        check_true("utility", "transfer true", is_transfer_request("我要找人工客服")),
        check_true("utility", "transfer false ai", not is_transfer_request("人工智能客服是什么")),
        check_true("utility", "transfer false normal", not is_transfer_request("客服在吗")),
        check_true("utility", "clarify short", needs_clarify("开通", [], "none")),
        check_true("utility", "clarify question false", not needs_clarify("怎么开通", [], "none")),
        check_true("utility", "clarify low vector", needs_clarify("设备异常", [0.61, 0.59], "vector_low")),
        check_true("utility", "clarify confident false", not needs_clarify("设备异常处理方案", [0.72, 0.61], "vector")),
        check_equal("utility", "vin uppercase", extract_vin("LFNAHUPMXT1E19383"), "LFNAHUPMXT1E19383"),
        check_equal("utility", "vin lowercase", extract_vin("lfnahupmxt1e19383"), "LFNAHUPMXT1E19383"),
        check_equal("utility", "vin in sentence", extract_vin("我的车架号是 LFNAHUPMXT1E19383"), "LFNAHUPMXT1E19383"),
        check_equal("utility", "vin invalid I", extract_vin("LFIAHUPMXT1E19383"), None),
        check_equal("utility", "fallback generic wifi", detect_business_area("套餐怎么续费", "wifi"), "wifi"),
    ]
    return cases


async def run_brand_cases(db) -> list[CaseResult]:
    service = BrandIdentificationService()
    results: list[CaseResult] = []
    keyword_cases = [
        ("极目设备离线", "极目(GPS+BD)", False),
        ("极目单北斗设备离线", "极目单北斗(DBD)", False),
        ("极目北斗怎么查SIM卡", "极目单北斗(DBD)", False),
        ("极目双模怎么重启", "极目(GPS+BD)", False),
        ("航天设备怎么重启", "航天", False),
        ("雅迅设备离线", "雅迅", False),
        ("启明设备密码是多少", "启明", False),
        ("有为终端号怎么查", "有为", False),
        ("通用问题", "通用", False),
        ("鱼快设备厂家代码是多少", None, True),
        ("这个是鱼快设备吗", None, True),
        ("请确认极目品牌", "极目(GPS+BD)", False),
        ("航天终端离线", "航天", False),
        ("雅迅SIM怎么查", "雅迅", False),
        ("启明设备重启", "启明", False),
    ]
    for query, expected_brand, ambiguous in keyword_cases:
        result = await service.identify_by_keyword(query)
        actual_brand = result.brand_name if result else None
        ok = actual_brand == expected_brand
        if ambiguous:
            ok = ok and result is not None and result.confidence < 0.8
        detail = (
            f"expected brand={expected_brand}, ambiguous={ambiguous}; "
            f"actual brand={actual_brand}, confidence={getattr(result, 'confidence', None)}"
        )
        results.append(check_true("brand", f"keyword:{query}", ok, detail))

    terminal_cases = []
    for i in range(5):
        terminal_cases.append((f"0012345678{i}", "雅迅"))
        terminal_cases.append((f"3112345678{i}", "启明"))
        terminal_cases.append((f"A12345{i}", "极目(GPS+BD)"))
        terminal_cases.append((f"1A2345{i}", "极目(GPS+BD)"))
        terminal_cases.append((f"HT12A{i}Z", "航天"))
        terminal_cases.append((f"90{123456 + i}", "航天"))

    for terminal_id, expected_brand in terminal_cases:
        result = await service.identify_by_terminal_id(db, terminal_id)
        actual_brand = result.brand_name if result else None
        results.append(
            check_equal("brand", f"terminal:{terminal_id}", actual_brand, expected_brand)
        )

    for query in ["未知品牌", "普通问题", "厂家是哪家", "设备异常", "这是什么设备"]:
        result = await service.identify_by_keyword(query)
        results.append(check_equal("brand", f"no keyword:{query}", result, None))
    return results


async def run_database_cases(db) -> list[CaseResult]:
    results: list[CaseResult] = []

    r = await db.execute(
        text(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = :schema AND table_name = 'operational_device'"
        ),
        {"schema": settings.MYSQL_DATABASE},
    )
    results.append(check_equal("database", "operational_device dropped", int(r.scalar() or 0), 0))

    r = await db.execute(text("SELECT COUNT(*) FROM operational_data"))
    operational_rows = int(r.scalar() or 0)
    results.append(check_true("database", "operational_data retained", operational_rows > 0, f"rows={operational_rows}"))

    results.append(
        check_true(
            "database",
            "mcu_verify_rule not registered in ORM",
            "mcu_verify_rule" not in BrandInfo.__table__.columns,
        )
    )

    r = await db.execute(text("SELECT COUNT(*) FROM business_knowledge_embedding WHERE status = 'published'"))
    embedding_count = int(r.scalar() or 0)
    results.append(check_equal("database", "embedding total count", embedding_count, 172))

    expected_counts = {"dashcam": 144, "wifi": 9, "data": 11, "refueling": 8}
    for area, expected in expected_counts.items():
        r = await db.execute(
            text(
                "SELECT COUNT(*) FROM business_knowledge_embedding "
                "WHERE status = 'published' AND business_area = :area"
            ),
            {"area": area},
        )
        results.append(check_equal("database", f"embedding count:{area}", int(r.scalar() or 0), expected))

    r = await db.execute(text("SELECT COUNT(*) FROM keyword_rule WHERE is_active = true"))
    active_rules = int(r.scalar() or 0)
    results.append(check_true("database", "keyword_rule active rows", active_rules >= 100, f"rows={active_rules}"))
    return results


async def run_exact_retrieval_cases(db) -> list[CaseResult]:
    results: list[CaseResult] = []
    for area, model in BUSINESS_KNOWLEDGE_MAP.items():
        stmt = (
            select(model.id, model.knowledge_code, model.standard_question)
            .where(model.status == "published")
            .order_by(model.id.asc())
        )
        rows = list((await db.execute(stmt)).all())
        for knowledge_id, code, question in rows:
            ids, scores, method = await knowledge_service.retrieve(db, question, area, top_k=50)
            ok = method == "exact" and knowledge_id in ids and bool(scores) and max(scores) >= 0.85
            detail = (
                f"area={area}, code={code}, expected_id={knowledge_id}, "
                f"method={method}, ids={ids[:8]}, scores={[round(s, 4) for s in scores[:8]]}"
            )
            results.append(check_true("retrieval_exact", f"{area}:{code}:{question}", ok, detail))
    return results


async def run_semantic_retrieval_cases(db) -> list[CaseResult]:
    loaded = await embedding_service.load_to_memory(db)
    if loaded < 172:
        return [check_true("retrieval_semantic", "embedding cache loaded", False, f"loaded={loaded}")]

    cases = [
        ("记录仪服务到期后怎么处理", "dashcam", "JL0139", None),
        ("SIM卡插在哪里", "dashcam", "JL0096", "SIM"),
        ("ICCID从哪里可以看到", "dashcam", None, "SIM"),
        ("终端编号在哪里查", "dashcam", None, "查询"),
        ("设备不在线要怎么排查", "dashcam", None, "在线"),
        ("车上热点开通流程", "wifi", "WF0005", None),
        ("WiFi套餐到期了怎么办", "wifi", None, "套餐"),
        ("车内无线网连不上", "wifi", None, "WiFi"),
        ("基础流量充了没到账", "data", "LL0010", None),
        ("基础流量充值入口在哪看", "data", "LL0010", None),
        ("油券退款要怎么弄", "refueling", None, "退款"),
        ("哪里能看今日油价", "refueling", None, "油"),
    ]

    results: list[CaseResult] = []
    for query, area, expected_code, expected_category_part in cases:
        ids, scores, method = await knowledge_service.retrieve(db, query, area, top_k=5)
        ok = bool(ids) and method not in {"keyword", "none"} and bool(scores) and scores[0] >= 0.5
        code: Optional[str] = None
        category = ""
        question = ""
        if ids:
            knowledge = await knowledge_service.get_knowledge_by_id(db, ids[0], area)
            code = getattr(knowledge, "knowledge_code", None)
            category = getattr(knowledge, "category_l2", None) or getattr(knowledge, "category", "") or ""
            question = getattr(knowledge, "standard_question", "") or ""
            if expected_code:
                ok = ok and code == expected_code
            if expected_category_part:
                ok = ok and (expected_category_part in category or expected_category_part in question)
        detail = (
            f"method={method}, ids={ids[:3]}, scores={[round(s, 4) for s in scores[:3]]}, "
            f"code={code}, category={category}, question={question}"
        )
        results.append(check_true("retrieval_semantic", query, ok, detail))
    return results


async def main() -> int:
    results: list[CaseResult] = []
    results.extend(run_business_cases())
    results.extend(await run_llm_understanding_cases())
    results.extend(run_intent_cases())
    results.extend(run_transfer_cases())
    results.extend(run_utility_cases())

    factory = get_session_factory()
    async with factory() as db:
        results.extend(await run_brand_cases(db))
        results.extend(await run_database_cases(db))
        results.extend(await run_exact_retrieval_cases(db))
        results.extend(await run_semantic_retrieval_cases(db))

    await close_db()

    if len(results) != 500:
        print(f"Generated {len(results)} cases, expected exactly 500")
        return 1

    passed = sum(1 for r in results if r.passed)
    failed = len(results) - passed

    by_group: dict[str, list[CaseResult]] = {}
    for result in results:
        by_group.setdefault(result.group, []).append(result)

    print(f"Total cases: {len(results)}")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    print("Groups:")
    for group, group_results in sorted(by_group.items()):
        group_passed = sum(1 for r in group_results if r.passed)
        print(f"  {group}: {group_passed}/{len(group_results)}")

    if failed:
        print("\nFailures:")
        for result in results:
            if not result.passed:
                print(f"- [{result.group}] {result.name}: {result.detail}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
