# 知识库检索服务
# 三层检索策略: L1精确匹配 → L2关键词匹配 → L3向量检索

import re
import logging
from typing import List, Tuple, Optional
import jieba
from sqlalchemy import select, or_, and_, func, text, literal
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.models import (
    KnowledgeAnswer,
    KnowledgeQuestionVariant,
    KnowledgeKeyword,
    KnowledgeAttachment,
)


logger = logging.getLogger(__name__)


class KnowledgeRetrievalService:
    """知识库三层检索服务

    L1 精确匹配: 品牌 + 知识类型 → SQL精确查询
    L2 关键词匹配: jieba分词 → 关键词权重累加 → 模糊匹配
    L3 向量检索: sentence-transformers 向量相似度
    """

    def __init__(self):
        # L3: 延迟加载向量模型
        self._embedding_model = None

    async def retrieve(
        self,
        db: AsyncSession,
        query: str,
        brand_id: Optional[int] = None,
        business_area: str = "dashcam",
        top_k: int = 5,
    ) -> Tuple[List[int], List[float], str]:
        """
        三层检索入口

        Returns:
            (knowledge_ids, scores, retrieval_method)
        """
        # L1: 精确匹配 (标准问题完全相等 / 问法变体LIKE)
        # 高分快速通道, 不调大模型
        ids, scores = await self._exact_match(db, query, brand_id, business_area, top_k)
        if ids and scores and max(scores) >= 0.8:
            return ids, scores, "exact"

        # L3: 大模型全量检索 (语义召回, 主路径)
        # 144条规模下, 把全部知识标准问题喂给大模型选最相关的 top5
        # 比关键词召回更准, 不受"设备""怎么办"等通用词干扰
        llm_ids = await self._llm_retrieve(db, query, business_area, top_k=5)
        if llm_ids:
            return llm_ids, [0.7 * (0.95 ** i) for i in range(len(llm_ids))], "llm_retrieve"

        # L3 失败, 回退 L2 关键词兜底
        kw_ids, kw_scores = await self._keyword_match(db, query, brand_id, business_area, top_k)
        if kw_ids and kw_scores:
            return kw_ids, kw_scores, "keyword"
        return [], [], "none"

    async def _llm_rerank(
        self, db: AsyncSession, query: str, candidate_ids: List[int]
    ) -> List[int]:
        """L2.5: 大模型 rerank — 对关键词召回的候选重新排序

        解决关键词匹配把通用词重合的无关条目排到前面的问题。
        把候选的标准问题交给大模型, 让它按语义相关度重排。
        """
        if not candidate_ids:
            return []
        stmt = select(KnowledgeAnswer.id, KnowledgeAnswer.standard_question).where(
            KnowledgeAnswer.id.in_(candidate_ids)
        )
        result = await db.execute(stmt)
        rows = result.all()
        if not rows:
            return []

        # 保持候选ID顺序 → 取标准问题
        cand_map = {r[0]: r[1] for r in rows}
        candidates = [{"id": cid, "question": cand_map.get(cid, "")} for cid in candidate_ids]

        try:
            from app.services.llm_service import get_llm
            llm = get_llm()
            reranked = await llm.retrieve(query, candidates)
            return reranked if reranked else candidate_ids
        except Exception as e:
            logger.warning(f"大模型rerank失败, 使用关键词原顺序: {e}")
            return candidate_ids

    async def _llm_retrieve(
        self, db: AsyncSession, query: str, business_area: str, top_k: int = 5
    ) -> List[int]:
        """L3: 大模型全量检索 — 从所有已发布知识里选最相关的 top_k

        144条规模下, 把全部知识(标准问题+主题分类)喂给大模型, 让它按语义选最相关的。
        主题标签(category_l2)帮助大模型理解知识分组, 例如把"设备离线"关联到
        "4G离线排查方法"主题下的6条品牌知识。
        """
        stmt = select(
            KnowledgeAnswer.id,
            KnowledgeAnswer.standard_question,
            KnowledgeAnswer.category_l2,
        ).where(
            KnowledgeAnswer.business_area == business_area,
            KnowledgeAnswer.status == "published",
            KnowledgeAnswer.auto_reply == True,
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
        self, db: AsyncSession, query: str, brand_id: Optional[int], business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """L1: 精确匹配 — 标准问题 + 问法变体"""
        conditions = [
            KnowledgeAnswer.business_area == business_area,
            KnowledgeAnswer.status == "published",
            KnowledgeAnswer.auto_reply == True,
        ]

        # 品牌过滤
        if brand_id:
            # 该品牌的知识 或 通用知识
            conditions.append(
                or_(
                    KnowledgeAnswer.manufacturer == None,  # 通用
                    KnowledgeAnswer.need_brand == False,
                    # 注: 品牌精确匹配在 brand_service 中处理
                )
            )

        # 精确匹配标准问题
        exact_stmt = (
            select(KnowledgeAnswer.id, literal(1.0).label("score"))
            .where(and_(*conditions, KnowledgeAnswer.standard_question == query))
            .limit(top_k)
        )
        exact_result = await db.execute(exact_stmt)
        exact_rows = exact_result.all()

        if exact_rows:
            return [r[0] for r in exact_rows], [r[1] for r in exact_rows]

        # 模糊匹配问法变体
        variant_stmt = (
            select(KnowledgeQuestionVariant.knowledge_id, literal(0.85).label("score"))
            .join(KnowledgeAnswer, KnowledgeQuestionVariant.knowledge_id == KnowledgeAnswer.id)
            .where(
                and_(
                    *conditions,
                    KnowledgeQuestionVariant.variant_text.like(f"%{query}%"),
                    KnowledgeQuestionVariant.is_active == True,
                )
            )
            .limit(top_k)
        )
        variant_result = await db.execute(variant_stmt)
        variant_rows = variant_result.all()

        return [r[0] for r in variant_rows], [r[1] for r in variant_rows]

    async def _keyword_match(
        self, db: AsyncSession, query: str, brand_id: Optional[int], business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """L2: 关键词匹配 — jieba分词 + 关键词权重"""
        # 分词
        words = list(jieba.cut(query))
        keywords = [w.strip() for w in words if len(w.strip()) >= 2]

        if not keywords:
            return [], []

        # 查询匹配的关键词
        conditions = [
            KnowledgeKeyword.keyword.in_(keywords),
            KnowledgeAnswer.business_area == business_area,
            KnowledgeAnswer.status == "published",
            KnowledgeAnswer.auto_reply == True,
        ]

        stmt = (
            select(
                KnowledgeKeyword.knowledge_id,
                func.sum(KnowledgeKeyword.weight).label("total_weight"),
                func.count(KnowledgeKeyword.id).label("match_count"),
            )
            .join(KnowledgeAnswer, KnowledgeKeyword.knowledge_id == KnowledgeAnswer.id)
            .where(and_(*conditions))
            .group_by(KnowledgeKeyword.knowledge_id)
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

    async def _vector_match(
        self, db: AsyncSession, query: str, business_area: str, top_k: int
    ) -> Tuple[List[int], List[float]]:
        """L3: 向量检索 (需要 sentence-transformers)"""
        # TODO: 集成向量数据库或本地embedding
        return [], []

    # ============================================
    # 知识获取
    # ============================================

    async def get_knowledge_by_id(self, db: AsyncSession, knowledge_id: int) -> Optional[KnowledgeAnswer]:
        """获取知识详情 (含关联数据)"""
        stmt = (
            select(KnowledgeAnswer)
            .options(
                selectinload(KnowledgeAnswer.attachments),
                selectinload(KnowledgeAnswer.keywords),
            )
            .where(KnowledgeAnswer.id == knowledge_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_knowledge_by_ids(self, db: AsyncSession, ids: List[int]) -> List[KnowledgeAnswer]:
        """批量获取知识"""
        if not ids:
            return []
        stmt = (
            select(KnowledgeAnswer)
            .options(selectinload(KnowledgeAnswer.attachments))
            .where(KnowledgeAnswer.id.in_(ids))
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())

    async def get_faq_cards(self, db: AsyncSession, business_area: str = "dashcam") -> List:
        """获取FAQ卡片"""
        from app.models import FAQCard
        stmt = (
            select(FAQCard)
            .where(
                FAQCard.business_area == business_area,
                FAQCard.is_active == True,
            )
            .order_by(FAQCard.display_order)
            .limit(10)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all())


# 全局单例
knowledge_service = KnowledgeRetrievalService()
