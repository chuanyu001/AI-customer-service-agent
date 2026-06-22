# Admin 管理后台 + Dashboard API

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models import Conversation, Message, HandoffTicket, OptimizationSample, EventLog
from app.schemas.common import BaseResponse, PaginatedResponse
from app.services.session_service import session_service

router = APIRouter(prefix="/admin", tags=["Admin"])


# ============================================
# Dashboard
# ============================================

@router.get("/dashboard/stats", response_model=BaseResponse)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
):
    """仪表盘核心指标"""
    stats = await session_service.get_dashboard_stats(db)
    return BaseResponse(data=stats)


@router.get("/dashboard/trends", response_model=BaseResponse)
async def get_trends(
    days: int = Query(default=7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
):
    """趋势数据 (按天)"""
    # 简化版: 返回最近N天的会话数
    from sqlalchemy import text
    stmt = text("""
        SELECT DATE(created_at) as date,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'transferred' THEN 1 ELSE 0 END) as transferred,
               SUM(CASE WHEN ai_resolved = 1 THEN 1 ELSE 0 END) as resolved
        FROM conversation
        WHERE created_at >= DATE_SUB(NOW(), INTERVAL :days DAY)
        GROUP BY DATE(created_at)
        ORDER BY date
    """)
    result = await db.execute(stmt, {"days": days})
    rows = result.fetchall()

    trends = [
        {"date": str(r[0]), "total": r[1], "transferred": r[2], "resolved": r[3]}
        for r in rows
    ]
    return BaseResponse(data=trends)


@router.get("/dashboard/kb-stats", response_model=BaseResponse)
async def get_kb_stats(
    db: AsyncSession = Depends(get_db),
):
    """知识库卡片统计数据"""
    from app.models import FAQCard
    stmt = select(
        func.count(FAQCard.id),
        func.sum(FAQCard.click_count),
    ).where(FAQCard.is_active == True)
    result = await db.execute(stmt)
    total_cards, total_clicks = result.one()

    return BaseResponse(data={
        "total_cards": total_cards or 0,
        "total_clicks": total_clicks or 0,
    })


# ============================================
# Conversations
# ============================================

@router.get("/conversations", response_model=BaseResponse)
async def list_conversations(
    status: Optional[str] = None,
    business_area: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """会话列表 (筛选+分页)"""
    conditions = []
    if status:
        conditions.append(Conversation.status == status)
    if business_area:
        conditions.append(Conversation.business_area == business_area)

    stmt = select(Conversation).where(*conditions) if conditions else select(Conversation)

    # 总数
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    # 分页
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Conversation.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    conversations = result.scalars().all()

    items = [
        {
            "id": c.id,
            "session_id": c.session_id,
            "user_id": c.user_id,
            "business_area": c.business_area,
            "status": c.status,
            "message_count": c.message_count,
            "ai_resolved": c.ai_resolved,
            "transfer_count": c.transfer_count,
            "started_at": c.started_at.isoformat() if c.started_at else None,
        }
        for c in conversations
    ]

    return BaseResponse(data=PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    ).model_dump())


@router.get("/conversations/{conv_id}", response_model=BaseResponse)
async def get_conversation_detail(
    conv_id: int,
    db: AsyncSession = Depends(get_db),
):
    """会话详情"""
    conv = await session_service.get_session_with_messages(db, str(conv_id))
    if not conv:
        # 尝试按ID查找
        stmt = select(Conversation).where(Conversation.id == conv_id)
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")

    messages = []
    for msg in conv.messages:
        messages.append({
            "message_id": msg.message_id,
            "seq": msg.seq,
            "role": msg.role,
            "content": msg.content,
            "action": msg.action,
            "reply_type": msg.reply_type,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        })

    return BaseResponse(data={
        "session_id": conv.session_id,
        "user_id": conv.user_id,
        "business_area": conv.business_area,
        "status": conv.status,
        "message_count": conv.message_count,
        "messages": messages,
    })


# ============================================
# Tickets
# ============================================

@router.get("/tickets", response_model=BaseResponse)
async def list_tickets(
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """转人工工单列表"""
    conditions = []
    if status:
        conditions.append(HandoffTicket.status == status)

    stmt = select(HandoffTicket).where(*conditions) if conditions else select(HandoffTicket)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = stmt.order_by(HandoffTicket.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    tickets = result.scalars().all()

    items = [
        {
            "ticket_id": t.ticket_id,
            "reason_type": t.reason_type,
            "reason_detail": t.reason_detail,
            "priority": t.priority,
            "status": t.status,
            "summary": t.summary,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        }
        for t in tickets
    ]

    return BaseResponse(data=PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    ).model_dump())


@router.put("/tickets/{ticket_id}", response_model=BaseResponse)
async def update_ticket(
    ticket_id: str,
    status: Optional[str] = None,
    assigned_to: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """更新工单状态"""
    stmt = select(HandoffTicket).where(HandoffTicket.ticket_id == ticket_id)
    result = await db.execute(stmt)
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="工单不存在")

    if status:
        ticket.status = status
    if assigned_to:
        ticket.assigned_to = assigned_to

    await db.commit()
    return BaseResponse(data={"ticket_id": ticket_id, "status": ticket.status})


# ============================================
# Samples
# ============================================

@router.get("/samples", response_model=BaseResponse)
async def list_samples(
    sample_type: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """优化样本池列表"""
    conditions = []
    if sample_type:
        conditions.append(OptimizationSample.sample_type == sample_type)
    if status:
        conditions.append(OptimizationSample.status == status)

    stmt = select(OptimizationSample).where(*conditions) if conditions else select(OptimizationSample)

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = stmt.order_by(OptimizationSample.created_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    samples = result.scalars().all()

    items = [
        {
            "id": s.id,
            "sample_type": s.sample_type,
            "user_query": s.user_query[:200],
            "actual_intent": s.actual_intent,
            "status": s.status,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in samples
    ]

    return BaseResponse(data=PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    ).model_dump())


# ============================================
# Configs
# ============================================

@router.get("/configs", response_model=BaseResponse)
async def get_configs(
    db: AsyncSession = Depends(get_db),
):
    """系统配置列表"""
    from app.models import SystemConfig
    stmt = select(SystemConfig)
    result = await db.execute(stmt)
    configs = result.scalars().all()

    items = [
        {"key": c.config_key, "value": c.config_value, "type": c.config_type, "description": c.description}
        for c in configs
    ]
    return BaseResponse(data=items)


# ============================================
# Health
# ============================================

@router.get("/health", response_model=BaseResponse)
async def admin_health():
    """Admin 健康检查"""
    return BaseResponse(data={"status": "ok"})
