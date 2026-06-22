# Evaluation 评价 API

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.common import BaseResponse
from app.services.session_service import session_service

router = APIRouter(prefix="/evaluation", tags=["Evaluation"])


class FeedbackRequest(BaseModel):
    """提交评价请求"""
    session_id: str = Field(..., description="会话ID")
    message_id: Optional[str] = Field(default=None, description="消息ID")
    rating: Optional[int] = Field(default=None, ge=1, le=5, description="评分 1-5")
    is_helpful: Optional[bool] = Field(default=None, description="是否有帮助")
    feedback_type: Optional[str] = Field(default=None, description="positive/negative/neutral")
    comment: Optional[str] = Field(default=None, description="文字反馈")


@router.post("/feedback", response_model=BaseResponse)
async def submit_feedback(
    req: FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """提交评价"""
    conv = await session_service.get_session(db, req.session_id)
    if not conv:
        return BaseResponse(code=404, message="会话不存在")

    # 查找消息
    msg_id = None
    if req.message_id:
        from app.models import Message
        from sqlalchemy import select
        stmt = select(Message).where(Message.message_id == req.message_id)
        result = await db.execute(stmt)
        msg = result.scalar_one_or_none()
        if msg:
            msg_id = msg.id

    feedback = await session_service.add_feedback(
        db=db,
        conversation_id=conv.id,
        message_id=msg_id or 0,
        rating=req.rating,
        is_helpful=req.is_helpful,
        feedback_type=req.feedback_type,
        comment=req.comment,
    )
    await db.commit()

    return BaseResponse(data={"id": feedback.id, "message": "评价提交成功"})


@router.get("/stats/{session_id}", response_model=BaseResponse)
async def get_evaluation_stats(
    session_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取会话维度评价统计"""
    stats = await session_service.get_feedback_stats(db, session_id)
    return BaseResponse(data=stats)
