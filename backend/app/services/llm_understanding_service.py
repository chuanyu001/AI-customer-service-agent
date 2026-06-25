"""LLM-driven intent understanding and session-context query rewriting.

The LLM is used only for understanding: intent classification, slot extraction,
and rewriting the current query with current-session context.  It must not
answer business questions directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from app.core.config import settings
from app.services.llm_service import get_llm
from app.services.rule_service import (
    classify_intent,
    detect_business_area,
    extract_vin,
    match_query_type,
    normalize_text,
)


logger = logging.getLogger(__name__)


ALLOWED_INTENTS = {
    "knowledge_query",
    "live_query",
    "clarify",
    "transfer_request",
    "greeting",
    "out_of_scope",
}
ALLOWED_BUSINESS_AREAS = {"dashcam", "wifi", "data", "refueling"}
ALLOWED_SLOT_KEYS = {"vin", "brand_name", "terminal_id", "iccid"}


@dataclass(frozen=True)
class LLMUnderstandingResult:
    intent_type: str
    confidence: float
    business_area: str
    query_type_code: Optional[str] = None
    rewritten_query: str = ""
    slots: dict[str, str] = field(default_factory=dict)
    need_clarify: bool = False
    clarify_question: str = ""
    method: str = "llm"
    fallback_used: bool = False
    raw_response: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent_type": self.intent_type,
            "confidence": self.confidence,
            "business_area": self.business_area,
            "query_type_code": self.query_type_code,
            "rewritten_query": self.rewritten_query,
            "slots": self.slots,
            "need_clarify": self.need_clarify,
            "clarify_question": self.clarify_question,
            "method": self.method,
            "fallback_used": self.fallback_used,
            "error": self.error,
        }


def _strip_json_markdown(response: str) -> str:
    text = (response or "").strip()
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(number, 1.0))


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "是", "需要"}
    return bool(value)


def _clean_slots(slots: Any) -> dict[str, str]:
    if not isinstance(slots, Mapping):
        return {}
    cleaned: dict[str, str] = {}
    for key in ALLOWED_SLOT_KEYS:
        value = slots.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            cleaned[key] = text
    if "vin" in cleaned:
        vin = extract_vin(cleaned["vin"])
        if vin:
            cleaned["vin"] = vin
    return cleaned


def fallback_understanding(
    query: str,
    fallback_business: str = "dashcam",
    *,
    reason: str = "",
) -> LLMUnderstandingResult:
    """Build a rule-based understanding result when LLM understanding fails."""
    decision = classify_intent(query, fallback_business)
    slots: dict[str, str] = {}
    vin = extract_vin(query)
    if vin:
        slots["vin"] = vin
    return LLMUnderstandingResult(
        intent_type=decision.intent_type,
        confidence=decision.confidence,
        business_area=decision.business_area,
        query_type_code=decision.query_type_code,
        rewritten_query=normalize_text(query),
        slots=slots,
        need_clarify=decision.should_clarify,
        method="rule_fallback",
        fallback_used=True,
        error=reason,
    )


def parse_understanding_response(
    response: str,
    query: str,
    fallback_business: str = "dashcam",
) -> LLMUnderstandingResult:
    """Parse and normalize the strict JSON returned by the LLM."""
    try:
        data = json.loads(_strip_json_markdown(response))
    except (TypeError, json.JSONDecodeError):
        return fallback_understanding(query, fallback_business, reason="invalid_json")

    if not isinstance(data, Mapping):
        return fallback_understanding(query, fallback_business, reason="non_object_json")

    rewritten_query = normalize_text(str(data.get("rewritten_query") or query))
    business_area = str(data.get("business_area") or "").strip()
    if business_area not in ALLOWED_BUSINESS_AREAS:
        business_area = detect_business_area(rewritten_query or query, fallback_business)

    intent_type = str(data.get("intent_type") or "").strip()
    if intent_type not in ALLOWED_INTENTS:
        intent_type = classify_intent(rewritten_query or query, business_area).intent_type

    query_type_code = data.get("query_type_code")
    if query_type_code is not None:
        query_type_code = str(query_type_code).strip() or None
    if not query_type_code:
        query_type_code = match_query_type(rewritten_query or query)

    slots = _clean_slots(data.get("slots"))
    vin = extract_vin(rewritten_query or query)
    if vin and "vin" not in slots:
        slots["vin"] = vin

    return LLMUnderstandingResult(
        intent_type=intent_type,
        confidence=_as_float(data.get("confidence"), 0.6),
        business_area=business_area,
        query_type_code=query_type_code,
        rewritten_query=rewritten_query or normalize_text(query),
        slots=slots,
        need_clarify=_as_bool(data.get("need_clarify")),
        clarify_question=str(data.get("clarify_question") or "").strip(),
        method="llm",
        raw_response=response or "",
    )


class LLMUnderstandingService:
    """LLM intent understanding service with deterministic rule fallback."""

    async def understand(
        self,
        query: str,
        *,
        business_area: str = "dashcam",
        history: Sequence[Mapping[str, Any]] = (),
        pending: Optional[Mapping[str, Any]] = None,
        memory: Optional[Mapping[str, Any]] = None,
    ) -> LLMUnderstandingResult:
        if not settings.ENABLE_LLM_UNDERSTANDING:
            return fallback_understanding(query, business_area, reason="disabled")

        messages = self._build_messages(query, business_area, history, pending, memory)
        try:
            llm = get_llm()
            response = await asyncio.wait_for(
                llm.chat(
                    messages,
                    temperature=0.1,
                    max_tokens=700,
                ),
                timeout=settings.LLM_UNDERSTANDING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning("LLM理解超时, 使用规则降级")
            return fallback_understanding(query, business_area, reason="timeout")
        except Exception as exc:
            logger.warning("LLM理解失败, 使用规则降级: %s", exc)
            return fallback_understanding(query, business_area, reason=str(exc))

        result = parse_understanding_response(response, query, business_area)
        if result.fallback_used:
            return result
        return result

    @staticmethod
    def _build_messages(
        query: str,
        business_area: str,
        history: Sequence[Mapping[str, Any]],
        pending: Optional[Mapping[str, Any]],
        memory: Optional[Mapping[str, Any]],
    ) -> list[dict[str, str]]:
        history_lines = []
        for item in history:
            role = str(item.get("role") or "")
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            history_lines.append(f"{role}: {content}")

        context = {
            "business_area_from_entry": business_area,
            "memory": memory or {},
            "pending": pending or {},
            "recent_messages": history_lines[-settings.LLM_UNDERSTANDING_HISTORY_LIMIT:],
        }
        system_prompt = (
            "你是客服Agent的意图理解器, 只负责理解用户真实意图、补全上下文、抽取槽位。"
            "你不能回答业务问题, 不能编造知识库外内容。\n"
            "必须只返回JSON对象, 不要Markdown, 不要解释。\n"
            "字段要求:\n"
            "{"
            "\"intent_type\":\"knowledge_query|live_query|clarify|transfer_request|greeting|out_of_scope\","
            "\"business_area\":\"dashcam|wifi|data|refueling\","
            "\"query_type_code\":\"QRYxxx或null\","
            "\"rewritten_query\":\"结合当前会话上下文补全后的完整问题\","
            "\"slots\":{\"vin\":\"\",\"brand_name\":\"\",\"terminal_id\":\"\",\"iccid\":\"\"},"
            "\"confidence\":0.0,"
            "\"need_clarify\":false,"
            "\"clarify_question\":\"\""
            "}\n"
            "判断规则:\n"
            "1. 用户问操作方法/规则/教程/故障排查, intent_type=knowledge_query。\n"
            "2. 用户查自己的设备数据、到期、在线状态、SIM/终端号, intent_type=live_query。\n"
            "3. 如果用户用'这个/它/那'等指代, 必须结合recent_messages和memory补全rewritten_query。\n"
            "4. 如果信息不足但还能追问, intent_type=clarify并给clarify_question。\n"
            "5. 不要生成答案, 只做理解。"
        )
        user_prompt = (
            f"当前用户消息: {query}\n\n"
            f"当前会话上下文(JSON):\n{json.dumps(context, ensure_ascii=False)}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]


llm_understanding_service = LLMUnderstandingService()
