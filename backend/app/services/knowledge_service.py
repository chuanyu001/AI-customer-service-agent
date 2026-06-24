# 知识库检索服务 (四业务分表版)
# 按 business_area 路由到对应模型: dashcam/wifi/data/refueling
# 三层检索: L1精确匹配 → L3大模型全量检索(主) → L2关键词兜底

import re
import logging
from typing import List, Tuple, Optional
import jieba
from sqlalchemy import select, or_, and_, func, text, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
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
        """三层检索入口

        Returns:
            (knowledge_ids, scores, retrieval_method)
        """
        # L1: 精确匹配 (标准问题完全相等 / 问法变体LIKE)
        ids, scores = await self._exact_match(db, query, business_area, top_k)
        if ids and scores and max(scores) >= 0.8:
            return ids, scores, "exact"

        # L3: 大模型全量检索 (主路径)
        llm_ids = await self._llm_retrieve(db, query, business_area, top_k=5)
        if llm_ids:
            return llm_ids, [0.7 * (0.95 ** i) for i in range(len(llm_ids))], "llm_retrieve"

        # L3 失败, 回退 L2 关键词兜底
        kw_ids, kw_scores = await self._keyword_match(db, query, business_area, top_k)
        if kw_ids and kw_scores:
            return kw_ids, kw_scores, "keyword"
        return [], [], "none"

    async def _llm_retrieve(
        self, db: AsyncSession, query: str, business_area: str, top_k: int = 5
    ) -> List[int]:
        """L3: 大模型全量检索 — 把该业务所有已发布知识喂给大模型选最相关的 top_k"""
        kn, var, kw, att, faq, cat_attr = self._get_models(business_area)
        cat_col = getattr(kn, cat_attr)

        stmt = select(kn.id, kn.standard_question, cat_col).where(
            kn.status == "published",
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
            return ids[:top_k] if ids else []
        except Exception as e:
            logger.warning(f"大模型检索失败: {e}")
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

        # 模糊匹配问法变体
        variant_stmt = (
            select(var.knowledge_id, literal(0.85).label("score"))
            .join(kn, var.knowledge_id == kn.id)
            .where(
                and_(
                    kn.status == "published",
                    var.variant_text.like(f"%{query}%"),
                    var.is_active == True,
                )
            )
            .limit(top_k)
        )
        variant_result = await db.execute(variant_stmt)
        variant_rows = variant_result.all()
        return [r[0] for r in variant_rows], [float(r[1]) for r in variant_rows]

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
