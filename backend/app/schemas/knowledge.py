# Knowledge 相关 Pydantic 模型

from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
from .common import PaginatedResponse


# ============================================
# Knowledge Answer
# ============================================

class KnowledgeCreate(BaseModel):
    """创建知识条目"""
    knowledge_code: Optional[str] = None
    business_area: str = "dashcam"
    category_l1: Optional[str] = None
    category_l2: Optional[str] = None
    manufacturer: Optional[str] = None
    standard_question: str = Field(..., min_length=1)
    standard_answer: str = Field(..., min_length=1)
    answer_type: str = "text"
    need_brand: bool = False
    need_attachment: bool = False
    risk_level: str = "low"
    auto_reply: bool = True
    status: str = "draft"


class KnowledgeUpdate(BaseModel):
    """更新知识条目"""
    category_l1: Optional[str] = None
    category_l2: Optional[str] = None
    manufacturer: Optional[str] = None
    standard_question: Optional[str] = None
    standard_answer: Optional[str] = None
    answer_type: Optional[str] = None
    need_brand: Optional[bool] = None
    need_attachment: Optional[bool] = None
    risk_level: Optional[str] = None
    auto_reply: Optional[bool] = None
    status: Optional[str] = None


class KnowledgeDetail(BaseModel):
    """知识条目详情"""
    id: int
    knowledge_code: str
    business_area: str
    category_l1: Optional[str]
    category_l2: Optional[str]
    manufacturer: Optional[str]
    standard_question: str
    standard_answer: str
    answer_type: str
    need_brand: bool
    need_attachment: bool
    risk_level: str
    status: str
    version: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]


class KnowledgeListItem(BaseModel):
    """知识列表项"""
    id: int
    knowledge_code: str
    category_l1: Optional[str]
    category_l2: Optional[str]
    standard_question: str
    status: str
    created_at: Optional[datetime]


# ============================================
# FAQ Card
# ============================================

class FAQCardItem(BaseModel):
    """FAQ卡片项"""
    id: int
    card_code: str
    title: str
    category: Optional[str]
    display_order: int


class FAQCardDetail(BaseModel):
    """FAQ卡片详情"""
    id: int
    card_code: str
    title: str
    category: Optional[str]
    answer: Optional[str] = None
    attachments: List[Dict[str, str]] = []


# ============================================
# Brand
# ============================================

class BrandItem(BaseModel):
    """品牌项"""
    id: int
    brand_code: str
    brand_name: str
    short_name: Optional[str]


# ============================================
# Import/Export
# ============================================

class ImportResult(BaseModel):
    """导入结果"""
    total_rows: int
    imported: int
    skipped: int
    errors: List[str] = []
    stats: Dict[str, int] = {}
