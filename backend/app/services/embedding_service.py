# 向量化服务 (火山方舟 Embedding API)
# 用于知识库语义检索的粗筛召回阶段
# 仅处理知识库文本, 不处理业务数据

import json
import hashlib
from typing import List, Tuple, Optional
import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.models import KnowledgeAnswer, KnowledgeEmbedding, KnowledgeQuestionVariant


class EmbeddingService:
    """向量化服务 (火山方舟 Embedding API)

    流程:
    1. 预计算: 把每条知识的 (标准问题 + 常见问法) 编码成向量, 存 knowledge_embedding 表
    2. 运行时: 把用户问题编码, 与库内所有向量算余弦相似度, 召回 top_k
    3. 加载到内存: 启动时全量加载, 避免每次查询都读DB
    """

    def __init__(self):
        self._client = None
        self._model = settings.EMBEDDING_MODEL
        # 内存缓存: [(knowledge_id, source_text, np.array向量)]
        self._cache: List[Tuple[int, str, np.ndarray]] = []
        self._loaded = False

    def _get_client(self):
        """惰性创建 OpenAI 兼容客户端 (火山方舟)"""
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.LLM_API_KEY,
            )
        return self._client

    def encode(self, text: str) -> np.ndarray:
        """编码单条文本 → 向量"""
        client = self._get_client()
        resp = client.embeddings.create(model=self._model, input=text)
        vec = resp.data[0].embedding
        return np.array(vec, dtype=np.float32)

    def encode_batch(self, texts: List[str]) -> np.ndarray:
        """批量编码 (火山方舟单次最多2048条, 这里分批)"""
        client = self._get_client()
        all_vecs = []
        batch_size = 64
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            resp = client.embeddings.create(model=self._model, input=batch)
            # 按 index 排序确保顺序
            resp.data.sort(key=lambda x: x.index)
            for d in resp.data:
                all_vecs.append(np.array(d.embedding, dtype=np.float32))
        return np.array(all_vecs)

    @staticmethod
    def _build_source_text(question: str, variants: List[str]) -> str:
        """拼接参与向量计算的源文本: 标准问题 + 常见问法"""
        parts = [question] + [v for v in variants if v]
        return " ".join(parts)

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        """L2归一化 (归一化后点积=余弦相似度)"""
        norm = np.linalg.norm(vec)
        if norm > 0:
            return vec / norm
        return vec

    # ============================================
    # 预计算 (脚本调用)
    # ============================================

    async def build_all_embeddings(self, db: AsyncSession, force: bool = False) -> dict:
        """预计算所有已发布知识的向量并入库

        Args:
            force: True=强制重算所有; False=只算新增/变更的
        """
        stmt = select(KnowledgeAnswer).where(
            KnowledgeAnswer.status == "published",
            KnowledgeAnswer.business_area == "dashcam",
        )
        result = await db.execute(stmt)
        knowledges = result.scalars().all()

        if not knowledges:
            return {"total": 0, "computed": 0, "skipped": 0}

        kid_list = [k.id for k in knowledges]
        var_stmt = select(KnowledgeQuestionVariant).where(
            KnowledgeQuestionVariant.knowledge_id.in_(kid_list),
            KnowledgeQuestionVariant.is_active == True,
        )
        var_result = await db.execute(var_stmt)
        variants_by_kid = {}
        for v in var_result.scalars().all():
            variants_by_kid.setdefault(v.knowledge_id, []).append(v.variant_text)

        emb_stmt = select(KnowledgeEmbedding).where(
            KnowledgeEmbedding.knowledge_id.in_(kid_list)
        )
        emb_result = await db.execute(emb_stmt)
        existing = {e.knowledge_id: e for e in emb_result.scalars().all()}

        computed = 0
        skipped = 0
        to_encode = []
        for k in knowledges:
            source = self._build_source_text(k.standard_question, variants_by_kid.get(k.id, []))
            h = self._hash_text(source)
            if not force and k.id in existing and existing[k.id].text_hash == h:
                skipped += 1
                continue
            to_encode.append((k, source))

        if to_encode:
            texts = [s for _, s in to_encode]
            vecs = self.encode_batch(texts)

            for (k, source), vec in zip(to_encode, vecs):
                h = self._hash_text(source)
                vec_json = json.dumps(vec.tolist())
                if k.id in existing:
                    existing[k.id].text_hash = h
                    existing[k.id].source_text = source
                    existing[k.id].embedding = vec_json
                    existing[k.id].dim = len(vec)
                    existing[k.id].model_name = self._model
                else:
                    db.add(KnowledgeEmbedding(
                        knowledge_id=k.id,
                        text_hash=h,
                        source_text=source,
                        embedding=vec_json,
                        model_name=self._model,
                        dim=len(vec),
                    ))
                computed += 1

        await db.commit()
        return {"total": len(knowledges), "computed": computed, "skipped": skipped}

    # ============================================
    # 内存加载 (启动时)
    # ============================================

    async def load_to_memory(self, db: AsyncSession) -> int:
        """把所有向量加载到内存 (服务启动时调用一次)"""
        stmt = select(KnowledgeEmbedding, KnowledgeAnswer).join(
            KnowledgeAnswer, KnowledgeEmbedding.knowledge_id == KnowledgeAnswer.id
        ).where(
            KnowledgeAnswer.status == "published",
        )
        result = await db.execute(stmt)
        rows = result.all()

        self._cache = []
        for emb, k in rows:
            try:
                vec = np.array(json.loads(emb.embedding), dtype=np.float32)
                vec = self._normalize(vec)
                self._cache.append((k.id, k.standard_question, vec))
            except (json.JSONDecodeError, ValueError):
                continue

        self._loaded = True
        return len(self._cache)

    # ============================================
    # 向量召回 (运行时)
    # ============================================

    async def search(self, query: str, top_k: int = 10) -> List[Tuple[int, float]]:
        """向量召回 top_k

        Returns:
            [(knowledge_id, score), ...] 按相似度降序
        """
        if not self._cache:
            return []

        query_vec = self._normalize(self.encode(query))
        scores = []
        for kid, _text, vec in self._cache:
            score = float(np.dot(query_vec, vec))
            scores.append((kid, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]


# 全局单例
embedding_service = EmbeddingService()
