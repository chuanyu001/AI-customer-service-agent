"""Run 100 regression cases for routing, intent, handoff, brand, and retrieval.

This script intentionally does not require pytest.  It is meant for quick local
verification after rule/retrieval changes.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass
from typing import Optional


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from app.core.database import close_db, get_session_factory  # noqa: E402
from app.services.brand_service import BrandIdentificationService  # noqa: E402
from app.services.embedding_service import embedding_service  # noqa: E402
from app.services.knowledge_service import knowledge_service  # noqa: E402
from app.services.rule_service import (  # noqa: E402
    classify_intent,
    detect_business_area,
    evaluate_transfer,
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


BUSINESS_CASES = [
    ("设备怎么续费", "dashcam", "dashcam"),
    ("行车记录仪怎么续费", "dashcam", "dashcam"),
    ("设备怎么充值", "dashcam", "dashcam"),
    ("记录仪设备怎么开通", "dashcam", "dashcam"),
    ("SIM卡怎么拔插", "dashcam", "dashcam"),
    ("怎么查询SIM卡号", "dashcam", "dashcam"),
    ("我的终端号是多少", "dashcam", "dashcam"),
    ("车架号怎么查设备", "dashcam", "dashcam"),
    ("北斗设备离线怎么办", "dashcam", "dashcam"),
    ("终端状态怎么看", "dashcam", "dashcam"),
    ("WiFi套餐怎么续费", "dashcam", "wifi"),
    ("怎么开通WiFi", "dashcam", "wifi"),
    ("车内wifi无法连接", "dashcam", "wifi"),
    ("热点密码在哪里", "dashcam", "wifi"),
    ("无线网络怎么改密码", "dashcam", "wifi"),
    ("随车wifi怎么购买", "dashcam", "wifi"),
    ("Wi-Fi连不上怎么办", "dashcam", "wifi"),
    ("WiFi发票怎么开", "dashcam", "wifi"),
    ("基础流量充值不到账怎么办", "dashcam", "data"),
    ("流量包怎么购买", "dashcam", "data"),
    ("流量套餐什么时候生效", "dashcam", "data"),
    ("流量卡怎么续费", "dashcam", "data"),
    ("青岛流量怎么充值", "dashcam", "data"),
    ("长春流量到期了怎么办", "dashcam", "data"),
    ("流量怎么开发票", "dashcam", "data"),
    ("加油券怎么退款", "dashcam", "refueling"),
    ("加油怎么开发票", "dashcam", "refueling"),
    ("油价在哪里看", "dashcam", "refueling"),
    ("柴油能不能用油券", "dashcam", "refueling"),
    ("发票怎么开", "dashcam", "dashcam"),
]


INTENT_CASES = [
    ("怎么查询SIM卡号", "dashcam", "knowledge_query", "dashcam", "QRY001"),
    ("设备怎么续费", "dashcam", "knowledge_query", "dashcam", "QRY007"),
    ("怎么查看设备在线状态", "dashcam", "knowledge_query", "dashcam", "QRY010"),
    ("设备离线怎么办", "dashcam", "knowledge_query", "dashcam", "QRY010"),
    ("SIM卡怎么拔插", "dashcam", "knowledge_query", "dashcam", "QRY001"),
    ("如何查询终端号", "dashcam", "knowledge_query", "dashcam", "QRY002"),
    ("设备密码是多少", "dashcam", "knowledge_query", "dashcam", None),
    ("我的服务什么时候到期", "dashcam", "live_query", "dashcam", "QRY007"),
    ("帮我查一下SIM卡号是多少", "dashcam", "live_query", "dashcam", "QRY001"),
    ("我的终端号是什么", "dashcam", "live_query", "dashcam", "QRY002"),
    ("我的设备状态怎么样", "dashcam", "live_query", "dashcam", "QRY010"),
    ("这台车离线了吗", "dashcam", "live_query", "dashcam", "QRY010"),
    ("我的车架号是LFNAHUPMXT1E19383，查一下设备号", "dashcam", "live_query", "dashcam", "QRY002"),
    ("LFNAHUPMXT1E19383 查询服务商", "dashcam", "live_query", "dashcam", "QRY004"),
    ("我的设备哪个服务商", "dashcam", "live_query", "dashcam", "QRY004"),
    ("怎么开通WiFi", "dashcam", "knowledge_query", "wifi", "QRY009"),
    ("WiFi套餐怎么续费", "dashcam", "knowledge_query", "wifi", "QRY007"),
    ("车内WiFi连不上怎么办", "dashcam", "knowledge_query", "wifi", None),
    ("基础流量怎么充值", "dashcam", "knowledge_query", "data", None),
    ("流量卡套餐怎么查询", "dashcam", "knowledge_query", "data", "QRY013"),
    ("流量充值不到账怎么办", "dashcam", "knowledge_query", "data", None),
    ("加油券怎么退款", "dashcam", "knowledge_query", "refueling", None),
    ("加油订单如何开发票", "dashcam", "knowledge_query", "refueling", None),
    ("我要转人工", "dashcam", "transfer_request", "dashcam", None),
    ("人工客服", "dashcam", "transfer_request", "dashcam", None),
    ("你好", "dashcam", "greeting", "dashcam", None),
    ("hello", "dashcam", "greeting", "dashcam", None),
    ("ICCID怎么查询", "dashcam", "knowledge_query", "dashcam", "QRY001"),
    ("帮我查ICCID是多少", "dashcam", "live_query", "dashcam", "QRY001"),
    ("套餐怎么续费", "wifi", "knowledge_query", "wifi", "QRY007"),
]


TRANSFER_CASES = [
    ("我要转人工", "dashcam", True, "user_request"),
    ("找人工客服", "dashcam", True, "user_request"),
    ("真人服务", "dashcam", True, "user_request"),
    ("转接人工电话", "dashcam", True, "user_request"),
    ("客服在吗", "dashcam", False, ""),
    ("人工智能客服是什么", "dashcam", False, ""),
    ("我要投诉", "dashcam", True, "risk"),
    ("我要打12315", "dashcam", True, "risk"),
    ("我要起诉你们", "dashcam", True, "risk"),
    ("媒体曝光你们", "dashcam", True, "risk"),
    ("欺诈骗人", "dashcam", True, "risk"),
    ("我要赔偿", "dashcam", True, "risk"),
    ("退款", "refueling", True, "risk"),
    ("我要退款", "refueling", True, "risk"),
    ("加油券怎么退款", "refueling", False, ""),
    ("加油券退款流程是什么", "refueling", False, ""),
    ("加油券不给退", "refueling", True, "risk"),
    ("帮我解绑设备", "dashcam", True, "out_of_scope"),
    ("帮我修改绑定", "dashcam", True, "out_of_scope"),
    ("设备怎么重启", "dashcam", False, ""),
]


BRAND_CASES = [
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
]


RETRIEVAL_CASES = [
    ("设备怎么续费", "dashcam", "JL0139", None),
    ("SIM卡怎么拔插", "dashcam", "JL0096", "SIM"),
    ("怎么开通WiFi", "wifi", "WF0005", None),
    ("基础流量充值不到账怎么办", "data", "LL0010", None),
    ("加油券怎么退款", "refueling", None, "退款"),
    ("油价在哪里看", "refueling", None, "油"),
    ("WiFi套餐怎么续费", "wifi", None, "套餐"),
    ("流量充值不到账怎么办", "data", "LL0010", None),
    ("设备离线怎么办", "dashcam", None, "离线"),
    ("如何查询终端号", "dashcam", None, "查询"),
]


def run_rule_cases() -> list[CaseResult]:
    results: list[CaseResult] = []

    for query, fallback, expected in BUSINESS_CASES:
        results.append(check_equal("business", query, detect_business_area(query, fallback), expected))

    for query, fallback, expected_intent, expected_area, expected_qtype in INTENT_CASES:
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

    for query, area, expected_transfer, expected_reason in TRANSFER_CASES:
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


async def run_brand_cases() -> list[CaseResult]:
    results: list[CaseResult] = []
    service = BrandIdentificationService()
    for query, expected_brand, ambiguous in BRAND_CASES:
        result = await service.identify_by_keyword(query)
        actual_brand = result.brand_name if result else None
        ok = actual_brand == expected_brand
        if ambiguous:
            ok = ok and result is not None and result.confidence < 0.8
        detail = (
            f"expected brand={expected_brand}, ambiguous={ambiguous}; "
            f"actual brand={actual_brand}, confidence={getattr(result, 'confidence', None)}"
        )
        results.append(check_true("brand", query, ok, detail))
    return results


async def run_retrieval_cases() -> list[CaseResult]:
    results: list[CaseResult] = []
    factory = get_session_factory()
    async with factory() as db:
        loaded = await embedding_service.load_to_memory(db)
        if loaded < 100:
            return [check_true("retrieval", "embedding cache loaded", False, f"loaded={loaded}")]

        for query, area, expected_code, expected_category_part in RETRIEVAL_CASES:
            ids, scores, method = await knowledge_service.retrieve(db, query, area, top_k=5)
            ok = bool(ids) and method != "keyword" and bool(scores) and scores[0] >= 0.55
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
            results.append(check_true("retrieval", query, ok, detail))

    await close_db()
    return results


async def main() -> int:
    results = run_rule_cases()
    results.extend(await run_brand_cases())
    results.extend(await run_retrieval_cases())
    if len(results) != 100:
        print(f"Generated {len(results)} cases, expected exactly 100")
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
