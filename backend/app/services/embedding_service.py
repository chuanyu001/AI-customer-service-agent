# 四业务知识库向量化服务
# 构建期: 预计算已发布知识向量并写入 MySQL
# 运行期: 启动加载到内存, 按 business_area 做余弦相似度召回

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models import (
    BUSINESS_KNOWLEDGE_MAP,
    BUSINESS_KEYWORD_MAP,
    BUSINESS_VARIANT_MAP,
    KnowledgeEmbedding,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingSource:
    business_area: str
    source_table: str
    knowledge_id: int
    knowledge_code: str
    source_text: str
    status: str


@dataclass(frozen=True)
class CachedEmbedding:
    business_area: str
    source_table: str
    knowledge_id: int
    knowledge_code: str
    source_text: str
    vector: np.ndarray


class EmbeddingService:
    """本地优先的知识向量服务.

    - 只处理知识库文本, 不处理运营事实数据。
    - 默认使用 sentence-transformers 本地模型。
    - 保留 volcengine provider 兼容旧配置, 但主路径推荐 local。
    """

    def __init__(self):
        self._model = None
        self._client = None
        self._cache: Dict[str, List[CachedEmbedding]] = {}
        self._loaded = False

    @property
    def model_name(self) -> str:
        if settings.EMBEDDING_PROVIDER == "local":
            return settings.EMBEDDING_LOCAL_PATH or settings.EMBEDDING_MODEL
        return settings.EMBEDDING_MODEL

    def _get_local_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            model_path = settings.EMBEDDING_LOCAL_PATH or settings.EMBEDDING_MODEL
            logger.info("加载本地 embedding 模型: %s", model_path)
            self._model = SentenceTransformer(model_path, device=settings.EMBEDDING_DEVICE)
        return self._model

    def _get_volcengine_client(self):
        if self._client is None:
            from openai import OpenAI
            import httpx

            self._client = OpenAI(
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.LLM_API_KEY,
                http_client=httpx.Client(proxy=None, timeout=30),
            )
        return self._client

    def encode(self, text: str) -> np.ndarray:
        """编码单条文本为 L2 归一化向量."""
        return self.encode_batch([text])[0]

    def encode_batch(self, texts: Sequence[str]) -> np.ndarray:
        """批量编码文本为 L2 归一化向量."""
        if not texts:
            return np.empty((0, 0), dtype=np.float32)

        if settings.EMBEDDING_PROVIDER == "volcengine":
            vectors = self._encode_batch_volcengine(texts)
        else:
            model = self._get_local_model()
            vectors = model.encode(
                list(texts),
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )

        vectors = np.asarray(vectors, dtype=np.float32)
        return np.vstack([self._normalize(v) for v in vectors])

    def _encode_batch_volcengine(self, texts: Sequence[str]) -> np.ndarray:
        client = self._get_volcengine_client()
        all_vecs = []
        batch_size = max(settings.EMBEDDING_BATCH_SIZE, 1)
        for i in range(0, len(texts), batch_size):
            batch = list(texts[i:i + batch_size])
            resp = client.embeddings.create(model=settings.EMBEDDING_MODEL, input=batch)
            resp.data.sort(key=lambda x: x.index)
            all_vecs.extend(np.array(d.embedding, dtype=np.float32) for d in resp.data)
        return np.asarray(all_vecs, dtype=np.float32)

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _dedupe(parts: Iterable[Optional[str]]) -> List[str]:
        seen = set()
        result = []
        for part in parts:
            text = (part or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
        return result

    @classmethod
    def build_source_text(
        cls,
        *,
        standard_question: str,
        category: Optional[str] = None,
        manufacturer: Optional[str] = None,
        common_phrasings: Optional[str] = None,
        variants: Optional[Sequence[str]] = None,
        keywords: Optional[Sequence[str]] = None,
    ) -> str:
        """拼接参与向量计算的检索文本.

        不拼完整答案, 避免答案里的泛化表述污染语义召回。
        """
        parts: List[Optional[str]] = [
            standard_question,
            category,
            manufacturer,
            common_phrasings,
        ]
        parts.extend(variants or [])
        parts.extend(keywords or [])
        return " ".join(cls._dedupe(parts))

    async def _collect_sources(
        self,
        db: AsyncSession,
        business_area: Optional[str] = None,
    ) -> List[EmbeddingSource]:
        areas = [business_area] if business_area else list(BUSINESS_KNOWLEDGE_MAP.keys())
        sources: List[EmbeddingSource] = []

        for area in areas:
            kn = BUSINESS_KNOWLEDGE_MAP.get(area)
            var = BUSINESS_VARIANT_MAP.get(area)
            kw = BUSINESS_KEYWORD_MAP.get(area)
            if kn is None:
                continue

            result = await db.execute(select(kn).where(kn.status == "published"))
            knowledges = list(result.scalars().all())
            if not knowledges:
                continue

            knowledge_ids = [k.id for k in knowledges]
            variants_by_id: Dict[int, List[str]] = {}
            keywords_by_id: Dict[int, List[str]] = {}

            if var is not None:
                var_result = await db.execute(
                    select(var).where(
                        and_(var.knowledge_id.in_(knowledge_ids), var.is_active == True)
                    )
                )
                for row in var_result.scalars().all():
                    variants_by_id.setdefault(row.knowledge_id, []).append(row.variant_text)

            if kw is not None:
                kw_result = await db.execute(select(kw).where(kw.knowledge_id.in_(knowledge_ids)))
                for row in kw_result.scalars().all():
                    keywords_by_id.setdefault(row.knowledge_id, []).append(row.keyword)

            for k in knowledges:
                category = getattr(k, "category_l2", None) or getattr(k, "category", None)
                source_text = self.build_source_text(
                    standard_question=k.standard_question,
                    category=category,
                    manufacturer=getattr(k, "manufacturer", None),
                    common_phrasings=getattr(k, "common_phrasings", None),
                    variants=variants_by_id.get(k.id, []),
                    keywords=keywords_by_id.get(k.id, []),
                )
                if not source_text:
                    continue
                sources.append(EmbeddingSource(
                    business_area=area,
                    source_table=kn.__tablename__,
                    knowledge_id=k.id,
                    knowledge_code=k.knowledge_code,
                    source_text=source_text,
                    status=k.status,
                ))

        return sources

    async def build_all_embeddings(
        self,
        db: AsyncSession,
        force: bool = False,
        business_area: Optional[str] = None,
    ) -> dict:
        """预计算四业务已发布知识向量并写入 MySQL."""
        sources = await self._collect_sources(db, business_area=business_area)
        if not sources:
            return {"total": 0, "computed": 0, "skipped": 0}

        existing_stmt = select(KnowledgeEmbedding)
        if business_area:
            existing_stmt = existing_stmt.where(KnowledgeEmbedding.business_area == business_area)
        existing_result = await db.execute(existing_stmt)
        existing = {
            (e.business_area, e.source_table, e.knowledge_id): e
            for e in existing_result.scalars().all()
        }

        to_encode: List[Tuple[EmbeddingSource, str]] = []
        skipped = 0
        for source in sources:
            text_hash = self._hash_text(source.source_text)
            key = (source.business_area, source.source_table, source.knowledge_id)
            old = existing.get(key)
            if not force and old and old.text_hash == text_hash and old.model_name == self.model_name:
                skipped += 1
                continue
            to_encode.append((source, text_hash))

        computed = 0
        if to_encode:
            vectors = self.encode_batch([source.source_text for source, _ in to_encode])
            for (source, text_hash), vec in zip(to_encode, vectors):
                key = (source.business_area, source.source_table, source.knowledge_id)
                payload = json.dumps(vec.tolist(), ensure_ascii=False)
                old = existing.get(key)
                if old:
                    old.knowledge_code = source.knowledge_code
                    old.text_hash = text_hash
                    old.source_text = source.source_text
                    old.embedding = payload
                    old.model_name = self.model_name
                    old.dim = len(vec)
                    old.status = source.status
                else:
                    db.add(KnowledgeEmbedding(
                        business_area=source.business_area,
                        source_table=source.source_table,
                        knowledge_id=source.knowledge_id,
                        knowledge_code=source.knowledge_code,
                        text_hash=text_hash,
                        source_text=source.source_text,
                        embedding=payload,
                        model_name=self.model_name,
                        dim=len(vec),
                        status=source.status,
                    ))
                computed += 1

        await db.commit()
        return {"total": len(sources), "computed": computed, "skipped": skipped}

    async def load_to_memory(self, db: AsyncSession) -> int:
        """加载已发布向量到内存."""
        result = await db.execute(
            select(KnowledgeEmbedding).where(KnowledgeEmbedding.status == "published")
        )
        rows = result.scalars().all()

        cache: Dict[str, List[CachedEmbedding]] = {}
        for row in rows:
            try:
                vec = np.array(json.loads(row.embedding), dtype=np.float32)
                vec = self._normalize(vec)
            except (TypeError, ValueError, json.JSONDecodeError):
                logger.warning("跳过损坏向量: area=%s kid=%s", row.business_area, row.knowledge_id)
                continue
            cache.setdefault(row.business_area, []).append(CachedEmbedding(
                business_area=row.business_area,
                source_table=row.source_table,
                knowledge_id=row.knowledge_id,
                knowledge_code=row.knowledge_code,
                source_text=row.source_text or "",
                vector=vec,
            ))

        self._cache = cache
        self._loaded = True
        return sum(len(items) for items in cache.values())

    async def search(
        self,
        query: str,
        business_area: str,
        top_k: Optional[int] = None,
    ) -> List[Tuple[int, float]]:
        """按业务域向量召回 top_k, 返回 [(knowledge_id, score)]."""
        if not settings.ENABLE_VECTOR_RETRIEVAL:
            return []

        records = self._cache.get(business_area, [])
        if not records:
            return []

        try:
            query_vec = self.encode(query)
        except Exception as e:
            logger.warning("查询向量生成失败, 跳过向量检索: %s", e)
            return []

        limit = top_k or settings.VECTOR_TOP_K
        scored = [
            (record.knowledge_id, float(np.dot(query_vec, record.vector)))
            for record in records
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:limit]


embedding_service = EmbeddingService()
