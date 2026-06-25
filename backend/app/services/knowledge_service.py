# 知识库检索服务 (四业务分表版)
# 按 business_area 路由到对应模型: dashcam/wifi/data/refueling
# 检索策略: 精确匹配 → 向量检索 → 大模型低置信候选重排

import re
import logging
from typing import Dict, List, Optional, Sequence, Tuple
import jieba
from sqlalchemy import select, or_, and_, func, text, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.config import settings
from app.models import (
    BUSINESS_KNOWLEDGE_MAP,
    BUSINESS_VARIANT_MAP,
    BUSINESS_KEYWORD_MAP,
    BUSINESS_ATTACHMENT_MAP,
    BUSINESS_FAQ_MAP,
)

logger = logging.getLogger(__name__)

# 业务 → 主题分类字段名 (dashcam用category_l2, 其他用category)
CATEGORY_ATTR_MAP = {
    "dashcam": "category_l2",
    "wifi": "category",
    "data": "category",
    "refueling": "category",
}


class KnowledgeRetrievalService:
    """知识库检索服务 (四业务分表, 按business_area路由)"""

    def _get_models(self, business_area: str):
        """获取业务对应的模型类"""
        kn = BUSINESS_KNOWLEDGE_MAP.get(business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
        var = BUSINESS_VARIANT_MAP.get(business_area)
        kw = BUSINESS_KEYWORD_MAP.get(business_area)
        att = BUSINESS_ATTACHMENT_MAP.get(business_area)
        faq = BUSINESS_FAQ_MAP.get(business_area)
        cat_attr = CATEGORY_ATTR_MAP.get(business_area, "category")
        return kn, var, kw, att, faq, cat_attr

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        business_area: str = "dashcam",
        top_k: int = 5,
    ) -> Tuple[List[int], List[float], str]:
        """知识问答检索入口.

        Returns:
            (knowledge_ids, scores, retrieval_method)
        """
        # L1: 精确匹配 (标准问题/问法变体完全相等)
        ids, scores = await self._exact_match(db, query, business_area, top_k)
        if ids and scores and max(scores) >= 0.8:
            return ids, scores, "exact"

        # L2: 向量召回 (正常主路径不调用大模型)
        vector_ids, vector_scores = await self._vector_match(query, business_area)
        if self._is_confident_vector(vector_scores):
            return vector_ids[:top_k], vector_scores[:top_k], "vector"

        # L3: 低置信候选重排. 只给大模型 topK 向量候选, 不再传全量知识库。
        if vector_ids and settings.ENABLE_LLM_RERANK:
            reranked = await self._llm_rerank(db, query, business_area, vector_ids, top_k)
            if reranked:
                return reranked, [0.66 * (0.95 ** i) for i in range(len(reranked))], "llm_rerank"

        # 大模型不可用或仍不确定时, 返回可解释的本地候选, 让上游按低置信/连续失败处理。
        if vector_ids and vector_scores and max(vector_scores) >= settings.VECTOR_LOW_SCORE:
            return vector_ids[:top_k], vector_scores[:top_k], "vector_low"
        return [], [], "none"

    async def retrieve_with_rewrite(
        self,
        db: AsyncSession,
        original_query: str,
        rewritten_query: str,
        business_area: str = "dashcam",
        top_k: int = 5,
    ) -> Tuple[List[int], List[float], str]:
        """Retrieval path for LLM understanding.

        Order is intentionally narrower than retrieve():
        original exact -> rewritten exact -> rewritten vector -> optional rerank.
        """
        original = (original_query or "").strip()
        rewritten = (rewritten_query or original).strip() or original

        ids, scores = await self._exact_match(db, original, business_area, top_k)
        if ids and scores and max(scores) >= 0.8:
            return ids, scores, "exact_original"

        if rewritten and rewritten != original:
            ids, scores = await self._exact_match(db, rewritten, business_area, top_k)
            if ids and scores and max(scores) >= 0.8:
                return ids, scores, "exact_rewritten"

        vector_ids, vector_scores = await self._vector_match(rewritten, business_area)
        if self._is_confident_vector(vector_scores):
            return vector_ids[:top_k], vector_scores[:top_k], "vector_rewritten"

        if vector_ids and settings.ENABLE_LLM_RERANK:
            reranked = await self._llm_rerank(db, rewritten, business_area, vector_ids, top_k)
            if reranked:
                return reranked, [0.66 * (0.95 ** i) for i in range(len(reranked))], "llm_rerank_rewritten"

        if vector_ids and vector_scores and max(vector_scores) >= settings.VECTOR_LOW_SCORE:
            return vector_ids[:top_k], vector_scores[:top_k], "vector_low_rewritten"
        return [], [], "none"

    async def _vector_match(
        self, query: str, business_area: str
    ) -> Tuple[List[int], List[float]]:
        """L2: 语义向量召回."""
        if not settings.ENABLE_VECTOR_RETRIEVAL:
            return [], []
        try:
            from app.services.embedding_service import embedding_service

            results = await embedding_service.search(
                query,
                business_area=business_area,
                top_k=settings.VECTOR_TOP_K,
            )
        except Exception as e:
            logger.warning("向量检索失败: %s", e)
            return [], []

        return [kid for kid, _ in results], [score for _, score in results]

    @staticmethod
    def _is_confident_vector(scores: Sequence[float]) -> bool:
        """判断向量 top1 是否可以直接采纳."""
        if not scores:
            return False
        top1 = scores[0]
        top2 = scores[1] if len(scores) > 1 else 0.0
        return (
            top1 >= settings.VECTOR_ACCEPT_SCORE
            and (top1 - top2) >= settings.VECTOR_MARGIN
        )

    @staticmethod
    def _merge_candidates(
        vector_ids: Sequence[int],
        vector_scores: Sequence[float],
        keyword_ids: Sequence[int],
        keyword_scores: Sequence[float],
        limit: int,
    ) -> List[Tuple[int, float]]:
        """合并向量和关键词候选, 保留每个知识的最高本地分."""
        merged: Dict[int, float] = {}
        for kid, score in zip(vector_ids, vector_scores):
            merged[kid] = max(merged.get(kid, 0.0), float(score))
        for kid, score in zip(keyword_ids, keyword_scores):
            merged[kid] = max(merged.get(kid, 0.0), float(score))
        return sorted(merged.items(), key=lambda item: item[1], reverse=True)[:limit]

    async def _llm_rerank(
        self,
        db: AsyncSession,
        query: str,
        business_area: str,
        candidate_ids: Sequence[int],
        top_k: int = 5,
    ) -> List[int]:
        """L4: 大模型只在本地候选内重排."""
        if not candidate_ids:
            return []

        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        cat_col = getattr(kn, cat_attr)

        stmt = select(kn.id, kn.standard_question, cat_col).where(
            and_(kn.status == "published", kn.id.in_(list(candidate_ids)))
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        candidates = [
            {"id": r[0], "question": r[1], "category": r[2] or ""}
            for r in rows
        ]
        try:
            from app.services.llm_service import get_llm
            llm = get_llm()
            ids = await llm.retrieve(query, candidates)
            candidate_set = set(candidate_ids)
            return [kid for kid in ids if kid in candidate_set][:top_k] if ids else []
        except Exception as e:
            logger.warning(f"大模型候选重排失败: {e}")
            return []

    async def _exact_match(
        self, db: AsyncSession, query: str, business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """L1: 精确匹配 — 标准问题 + 问法变体"""
        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        if var is None:
            return [], []

        # 精确匹配标准问题
        exact_stmt = (
            select(kn.id, literal(1.0).label("score"))
            .where(and_(kn.status == "published", kn.standard_question == query))
            .limit(top_k)
        )
        exact_result = await db.execute(exact_stmt)
        exact_rows = exact_result.all()
        if exact_rows:
            return [r[0] for r in exact_rows], [float(r[1]) for r in exact_rows]

        rule_ids, rule_scores = await self._dashcam_rule_boost_match(db, query, business_area, top_k)
        if rule_ids:
            return rule_ids, rule_scores

        intent_ids, intent_scores = await self._dashcam_query_method_match(db, query, business_area, top_k)
        if intent_ids:
            return intent_ids, intent_scores

        # 精确匹配问法变体, 避免 LIKE 把短问句扩散到多个相近知识条目。
        variant_stmt = (
            select(var.knowledge_id, literal(0.85).label("score"))
            .join(kn, var.knowledge_id == kn.id)
            .where(
                and_(
                    kn.status == "published",
                    var.variant_text == query,
                    var.is_active == True,
                )
            )
            .limit(top_k)
        )
        variant_result = await db.execute(variant_stmt)
        variant_rows = variant_result.all()
        if len(variant_rows) > 1:
            return [], []
        return [r[0] for r in variant_rows], [float(r[1]) for r in variant_rows]

    async def _dashcam_rule_boost_match(
        self, db: AsyncSession, query: str, business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """Narrow deterministic boosts for high-frequency dashcam tutorial intents."""
        if business_area != "dashcam":
            return [], []

        q = (query or "").lower()
        if not q:
            return [], []

        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)

        if re.search(r"(续费|续约|到期|过期)", q) and re.search(r"(怎么|如何|怎样|处理|怎么办|续|开通)", q):
            stmt = (
                select(kn.id, literal(0.92).label("score"))
                .where(
                    and_(
                        kn.status == "published",
                        or_(kn.category_l2.like("%续费%"), kn.standard_question.like("%续费%")),
                    )
                )
                .limit(top_k)
            )
            result = await db.execute(stmt)
            rows = result.all()
            return [r[0] for r in rows], [float(r[1]) for r in rows]

        return [], []

    async def _dashcam_query_method_match(
        self, db: AsyncSession, query: str, business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """Narrow exact boost for dashcam "how to query SIM/terminal" questions."""
        if business_area != "dashcam":
            return [], []

        q = (query or "").lower()
        if re.search(r"(拔插|插拔|安装|更换|取出|拆|插.*哪|插入|插卡|卡槽)", q):
            return [], []
        has_instruction = re.search(r"(怎么|如何|怎样|哪里|在哪|查询|查看)", q)
        has_identifier = re.search(r"(sim|卡号|iccid|终端号|终端编号|设备号|设备编号|设备id|device.?id)", q)
        if not (has_instruction and has_identifier):
            return [], []

        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        stmt = (
            select(kn.id, literal(0.9).label("score"))
            .where(and_(kn.status == "published", kn.category_l2 == "查询SIM/ID方法"))
            .limit(top_k)
        )
        result = await db.execute(stmt)
        rows = result.all()
        return [r[0] for r in rows], [float(r[1]) for r in rows]

    async def _keyword_match(
        self, db: AsyncSession, query: str, business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """L2: 关键词匹配 — jieba分词 + 关键词权重"""
        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        if kw is None:
            return [], []

        words = list(jieba.cut(query))
        keywords = [w.strip() for w in words if len(w.strip()) >= 2]
        if not keywords:
            return [], []

        stmt = (
            select(
                kw.knowledge_id,
                func.sum(kw.weight).label("total_weight"),
                func.count(kw.id).label("match_count"),
            )
            .join(kn, kw.knowledge_id == kn.id)
            .where(and_(kw.keyword.in_(keywords), kn.status == "published"))
            .group_by(kw.knowledge_id)
            .order_by(text("total_weight DESC"), text("match_count DESC"))
            .limit(top_k)
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return [], []

        max_weight = rows[0][1]
        ids = [r[0] for r in rows]
        scores = [min(r[1] / max(max_weight, 1), 0.95) for r in rows]
        return ids, scores

    # ============================================
    # 知识获取
    # ============================================

    async def get_knowledge_by_id(
        self, db: AsyncSession, knowledge_id: int, business_area: str = "dashcam"
    ):
        """获取知识详情 (含关联数据, dashcam含附件)"""
        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        stmt = select(kn).where(kn.id == knowledge_id)

        # dashcam 预加载附件和关键词
        if att is not None and hasattr(kn, "attachments"):
            stmt = stmt.options(selectinload(kn.attachments))
        if hasattr(kn, "keywords"):
            stmt = stmt.options(selectinload(kn.keywords))

        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_faq_cards(self, db: AsyncSession, business_area: str = "dashcam") -> List:
        """获取FAQ卡片"""
        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        if faq is None:
            return []
        stmt = (
            select(faq)
            .where(faq.is_active == True)
            .order_by(faq.display_order)
            .limit(10)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


# 全局单例
knowledge_service = KnowledgeRetrievalService()
