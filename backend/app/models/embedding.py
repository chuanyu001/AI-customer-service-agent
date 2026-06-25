# 知识向量存储 ORM
# 存储知识条目的文本向量, 用于语义检索 (粗筛召回)
# 仅覆盖知识库, 不含业务数据 (业务数据走SQL精确查询)

from sqlalchemy import Column, String, Text, Integer, DateTime, Index, UniqueConstraint
from sqlalchemy.sql import func
from app.core.database import Base


class KnowledgeEmbedding(Base):
    """四业务通用知识向量表

    每条知识计算一个向量, 启动时按业务域加载到内存做余弦相似度召回。
    旧的 knowledge_embedding 表仍可保留给 legacy knowledge_answer 使用,
    新检索链路只读写本表, 避免旧外键阻挡 WiFi/流量/加油知识入库。
    """
    __tablename__ = "business_knowledge_embedding"

    id = Column(Integer, primary_key=True, autoincrement=True)
    business_area = Column(String(32), nullable=False, index=True, comment="业务领域: dashcam/wifi/data/refueling")
    source_table = Column(String(64), nullable=False, comment="来源知识表")
    knowledge_id = Column(Integer, nullable=False, index=True, comment="来源知识ID")
    knowledge_code = Column(String(64), nullable=False, index=True, comment="知识编码")
    text_hash = Column(String(64), nullable=False, comment="源文本hash, 用于判断是否需要重算")
    source_text = Column(Text, comment="参与向量计算的源文本")
    embedding = Column(Text, nullable=False, comment="向量JSON, 如 [0.01, -0.03, ...]")
    model_name = Column(String(128), comment="生成向量的模型名")
    dim = Column(Integer, comment="向量维度")
    status = Column(String(32), default="published", comment="知识状态快照")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("business_area", "source_table", "knowledge_id", name="uq_business_embedding_source"),
        Index("idx_business_embedding_area", "business_area"),
        Index("idx_business_embedding_kid", "business_area", "knowledge_id"),
    )
