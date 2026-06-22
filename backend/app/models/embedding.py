# 知识向量存储 ORM
# 存储知识条目的文本向量, 用于语义检索 (粗筛召回)
# 仅覆盖知识库, 不含业务数据 (业务数据走SQL精确查询)

from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey, Index
from sqlalchemy.sql import func
from app.core.database import Base


class KnowledgeEmbedding(Base):
    """知识向量表

    每条知识计算一个向量 (基于 standard_question + 常见问法),
    启动时全量加载到内存做余弦相似度粗筛。
    """
    __tablename__ = "knowledge_embedding"

    id = Column(Integer, primary_key=True, autoincrement=True)
    knowledge_id = Column(Integer, ForeignKey("knowledge_answer.id", ondelete="CASCADE"), nullable=False, index=True, comment="关联知识ID")
    text_hash = Column(String(64), nullable=False, comment="源文本hash, 用于判断是否需要重算")
    source_text = Column(Text, comment="参与向量计算的源文本")
    embedding = Column(Text, nullable=False, comment="向量JSON, 如 [0.01, -0.03, ...]")
    model_name = Column(String(128), comment="生成向量的模型名")
    dim = Column(Integer, comment="向量维度")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_knowledge_embedding_kid", "knowledge_id"),
    )
