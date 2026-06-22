# 会话管理服务

import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Conversation, Message, AnswerFeedback
from app.core.redis_client import get_session_state, set_session_state
from app.core.config import settings


class SessionService:
    """会话管理服务"""

    @staticmethod
    async def create_session(
        db: AsyncSession,
        user_id: Optional[str] = None,
        business_area: str = "dashcam",
        entry_point: Optional[str] = None,
        channel: str = "miniprogram",
    ) -> Conversation:
        """创建新会话"""
        session_id = str(uuid.uuid4())

        conversation = Conversation(
            session_id=session_id,
            user_id=user_id,
            user_type="registered" if user_id else "guest",
            channel=channel,
            entry_point=entry_point,
            business_area=business_area,
            status="active",
            message_count=0,
            consecutive_fail=0,
        )
        db.add(conversation)
        await db.flush()

        # 初始化Redis会话状态
        await set_session_state(session_id, {
            "collected_slots": {},
            "dialogue_round": 0,
            "consecutive_fail": 0,
            "last_brand": None,
            "business_area": business_area,
            "created_at": datetime.now().isoformat(),
        })

        return conversation

    @staticmethod
    async def get_session(db: AsyncSession, session_id: str) -> Optional[Conversation]:
        """获取会话"""
        stmt = (
            select(Conversation)
            .where(Conversation.session_id == session_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_session_with_messages(
        db: AsyncSession, session_id: str
    ) -> Optional[Conversation]:
        """获取会话 (含消息)"""
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.messages))
            .where(Conversation.session_id == session_id)
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def add_message(
        db: AsyncSession,
        conversation_id: int,
        role: str,
        content: str,
        content_type: str = "text",
        **kwargs,
    ) -> Message:
        """添加消息"""
        # 获取当前序号
        stmt = select(func.max(Message.seq)).where(
            Message.conversation_id == conversation_id
        )
        result = await db.execute(stmt)
        max_seq = result.scalar() or 0

        message = Message(
            conversation_id=conversation_id,
            message_id=str(uuid.uuid4()),
            seq=max_seq + 1,
            role=role,
            content=content,
            content_type=content_type,
            **kwargs,
        )
        db.add(message)

        # 更新会话消息计数
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv:
            conv.message_count = max_seq + 1
            conv.updated_at = datetime.now()

        await db.flush()
        return message

    @staticmethod
    async def update_session_status(
        db: AsyncSession, session_id: str, status: str, **kwargs
    ):
        """更新会话状态"""
        conv = await SessionService.get_session(db, session_id)
        if conv:
            conv.status = status
            for key, value in kwargs.items():
                if hasattr(conv, key):
                    setattr(conv, key, value)
            if status in ("resolved", "closed"):
                conv.ended_at = datetime.now()
            await db.flush()

    @staticmethod
    async def update_consecutive_fail(
        db: AsyncSession, session_id: str, increment: bool = True
    ):
        """更新连续失败计数"""
        conv = await SessionService.get_session(db, session_id)
        if conv:
            if increment:
                conv.consecutive_fail += 1
            else:
                conv.consecutive_fail = 0
            await db.flush()

    @staticmethod
    async def set_pending_context(
        db: AsyncSession, session_id: str, pending: Dict[str, Any]
    ):
        """写入待处理上下文 (如品牌追问: {type:"brand_collection", knowledge_id, category_l2})

        下一轮请求会读取并据此处理, 处理完成后清空。
        """
        conv = await SessionService.get_session(db, session_id)
        if conv:
            meta = conv.extra_metadata or {}
            meta["pending"] = pending
            conv.extra_metadata = meta
            await db.flush()

    @staticmethod
    async def get_pending_context(
        db: AsyncSession, session_id: str
    ) -> Optional[Dict[str, Any]]:
        """读取待处理上下文 (不清空, 由调用方处理完后清空)"""
        conv = await SessionService.get_session(db, session_id)
        if conv and conv.extra_metadata:
            return conv.extra_metadata.get("pending")
        return None

    @staticmethod
    async def clear_pending_context(db: AsyncSession, session_id: str):
        """清空待处理上下文"""
        conv = await SessionService.get_session(db, session_id)
        if conv and conv.extra_metadata:
            meta = conv.extra_metadata
            meta.pop("pending", None)
            conv.extra_metadata = meta
            await db.flush()

    @staticmethod
    async def add_feedback(
        db: AsyncSession,
        conversation_id: int,
        message_id: int,
        rating: Optional[int] = None,
        is_helpful: Optional[bool] = None,
        feedback_type: Optional[str] = None,
        comment: Optional[str] = None,
    ) -> AnswerFeedback:
        """添加评价"""
        feedback = AnswerFeedback(
            conversation_id=conversation_id,
            message_id=message_id,
            rating=rating,
            is_helpful=is_helpful,
            feedback_type=feedback_type,
            comment=comment,
        )
        db.add(feedback)
        await db.flush()
        return feedback

    @staticmethod
    async def get_feedback_stats(
        db: AsyncSession, session_id: str
    ) -> Dict[str, Any]:
        """获取会话评价统计"""
        conv = await SessionService.get_session(db, session_id)
        if not conv:
            return {}

        stmt = select(AnswerFeedback).where(
            AnswerFeedback.conversation_id == conv.id
        )
        result = await db.execute(stmt)
        feedbacks = result.scalars().all()

        if not feedbacks:
            return {"total": 0}

        ratings = [f.rating for f in feedbacks if f.rating]
        helpful_count = sum(1 for f in feedbacks if f.is_helpful)

        return {
            "total": len(feedbacks),
            "avg_rating": sum(ratings) / len(ratings) if ratings else 0,
            "helpful_count": helpful_count,
            "helpful_rate": helpful_count / len(feedbacks) if feedbacks else 0,
        }

    @staticmethod
    async def get_dashboard_stats(db: AsyncSession) -> Dict[str, Any]:
        """获取仪表盘统计"""
        # 总会话数
        total_stmt = select(func.count(Conversation.id))
        total_result = await db.execute(total_stmt)
        total_sessions = total_result.scalar() or 0

        # AI解决数
        resolved_stmt = select(func.count(Conversation.id)).where(
            Conversation.ai_resolved == True
        )
        resolved_result = await db.execute(resolved_stmt)
        resolved = resolved_result.scalar() or 0

        # 转人工数
        transferred_stmt = select(func.count(Conversation.id)).where(
            Conversation.status == "transferred"
        )
        transferred_result = await db.execute(transferred_stmt)
        transferred = transferred_result.scalar() or 0

        # 满意度
        feedback_stmt = select(
            func.avg(AnswerFeedback.rating),
            func.count(AnswerFeedback.id),
        )
        feedback_result = await db.execute(feedback_stmt)
        avg_rating, feedback_count = feedback_result.one()

        return {
            "total_sessions": total_sessions,
            "ai_resolved": resolved,
            "transfer_count": transferred,
            "transfer_rate": transferred / total_sessions if total_sessions > 0 else 0,
            "ai_resolution_rate": resolved / total_sessions if total_sessions > 0 else 0,
            "avg_rating": float(avg_rating) if avg_rating else 0,
            "feedback_count": feedback_count or 0,
        }


# 全局单例
session_service = SessionService()
