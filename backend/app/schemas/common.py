# 通用 Pydantic 模型

from typing import Optional, Any, Dict, List
from pydantic import BaseModel, Field


class BaseResponse(BaseModel):
    """统一响应格式"""
    code: int = 0
    message: str = "success"
    data: Optional[Any] = None
    trace_id: Optional[str] = None


class PaginationParams(BaseModel):
    """分页参数"""
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class PaginatedResponse(BaseModel):
    """分页响应"""
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int
