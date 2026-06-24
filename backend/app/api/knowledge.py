# Knowledge 知识库管理 API

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.models import KnowledgeAnswer, FAQCard, BrandInfo, KnowledgeQuestionVariant, BUSINESS_KNOWLEDGE_MAP, BUSINESS_FAQ_MAP
from app.schemas.knowledge import (
    KnowledgeCreate, KnowledgeUpdate, KnowledgeDetail, KnowledgeListItem,
    FAQCardItem, FAQCardDetail, BrandItem, ImportResult,
)
from app.schemas.common import BaseResponse, PaginatedResponse
from app.services.knowledge_service import knowledge_service

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])


# ============================================
# FAQ Cards
# ============================================

@router.get("/faq-cards", response_model=BaseResponse)
async def get_faq_cards(
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """获取FAQ卡片列表"""
    cards = await knowledge_service.get_faq_cards(db, business_area)
    items = [
        FAQCardItem(
            id=c.id,
            card_code=c.card_code,
            title=c.title,
            category=c.category,
            display_order=c.display_order,
        ) for c in cards
    ]
    return BaseResponse(data=[item.model_dump() for item in items])


@router.get("/faq-cards/{card_id}", response_model=BaseResponse)
async def get_faq_card_detail(
    card_id: int,
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """获取FAQ卡片详情 (含答案, 按business_area路由)"""
    FaqModel = BUSINESS_FAQ_MAP.get(business_area, BUSINESS_FAQ_MAP["dashcam"])
    stmt = select(FaqModel).where(FaqModel.id == card_id)
    result = await db.execute(stmt)
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(status_code=404, detail="卡片不存在")

    answer = None
    attachments = []
    if card.knowledge_id:
        knowledge = await knowledge_service.get_knowledge_by_id(db, card.knowledge_id, business_area)
        if knowledge:
            answer = knowledge.standard_answer
            if getattr(knowledge, "need_attachment", False) and hasattr(knowledge, "attachments"):
                for att in knowledge.attachments:
                    attachments.append({"type": att.file_type or "link", "url": att.file_url, "name": att.file_name})

    return BaseResponse(data=FAQCardDetail(
        id=card.id,
        card_code=card.card_code,
        title=card.title,
        category=card.category,
        answer=answer,
        attachments=attachments,
    ).model_dump())


# ============================================
# Knowledge Entries
# ============================================

@router.get("/entries", response_model=BaseResponse)
async def list_knowledge_entries(
    business_area: str = "dashcam",
    category_l1: Optional[str] = None,
    status: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """知识条目列表 (分页+筛选, 按business_area路由到对应业务表)"""
    KnModel = BUSINESS_KNOWLEDGE_MAP.get(business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
    conditions = [KnModel.status == "published"] if status is None else [KnModel.status == status]
    # category_l1 仅dashcam有; 其他业务用category
    cat_col = getattr(KnModel, "category_l1", None) or getattr(KnModel, "category", None)
    if category_l1 and cat_col is not None:
        conditions.append(cat_col == category_l1)

    stmt = select(KnModel).where(*conditions)
    if keyword:
        stmt = stmt.where(
            KnModel.standard_question.contains(keyword) |
            KnModel.standard_answer.contains(keyword)
        )

    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_result = await db.execute(count_stmt)
    total = count_result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = stmt.order_by(KnModel.updated_at.desc()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    entries = result.scalars().all()

    items = [
        KnowledgeListItem(
            id=e.id,
            knowledge_code=e.knowledge_code,
            category_l1=getattr(e, "category_l1", None) or getattr(e, "category", None),
            category_l2=getattr(e, "category_l2", None),
            standard_question=e.standard_question,
            status=e.status,
            created_at=e.created_at,
        ) for e in entries
    ]

    return BaseResponse(data=PaginatedResponse(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    ).model_dump())


@router.get("/entries/{entry_id}", response_model=BaseResponse)
async def get_knowledge_entry(
    entry_id: int,
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """获取知识条目详情 (按business_area路由)"""
    knowledge = await knowledge_service.get_knowledge_by_id(db, entry_id, business_area)
    if not knowledge:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    return BaseResponse(data=KnowledgeDetail(
        id=knowledge.id,
        knowledge_code=knowledge.knowledge_code,
        business_area=business_area,
        category_l1=getattr(knowledge, "category_l1", None),
        category_l2=getattr(knowledge, "category_l2", None) or getattr(knowledge, "category", None),
        manufacturer=getattr(knowledge, "manufacturer", None),
        standard_question=knowledge.standard_question,
        standard_answer=knowledge.standard_answer,
        answer_type=getattr(knowledge, "answer_type", "text"),
        need_brand=getattr(knowledge, "need_brand", False),
        need_attachment=getattr(knowledge, "need_attachment", False),
        risk_level=getattr(knowledge, "risk_level", "low"),
        status=knowledge.status,
        version=getattr(knowledge, "version", 1),
        created_at=knowledge.created_at,
        updated_at=knowledge.updated_at,
    ).model_dump())


@router.post("/entries", response_model=BaseResponse)
async def create_knowledge_entry(
    req: KnowledgeCreate,
    db: AsyncSession = Depends(get_db),
):
    """新增知识条目 (按business_area路由到对应业务表)"""
    import uuid
    KnModel = BUSINESS_KNOWLEDGE_MAP.get(req.business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
    entry = KnModel(
        knowledge_code=req.knowledge_code or f"KA-{uuid.uuid4().hex[:12]}",
        standard_question=req.standard_question,
        standard_answer=req.standard_answer,
        status=req.status,
    )
    # 设置业务特有字段 (仅当模型有该列时)
    if hasattr(entry, "category_l1"):
        entry.category_l1 = req.category_l1
    if hasattr(entry, "category_l2"):
        entry.category_l2 = req.category_l2
    elif hasattr(entry, "category"):
        entry.category = req.category_l2 or req.category_l1
    for fld in ("manufacturer", "answer_type", "need_brand", "need_attachment", "risk_level", "auto_reply"):
        if hasattr(entry, fld):
            setattr(entry, fld, getattr(req, fld, None))
    db.add(entry)
    await db.commit()
    await db.refresh(entry)

    return BaseResponse(data={"id": entry.id, "knowledge_code": entry.knowledge_code})


@router.put("/entries/{entry_id}", response_model=BaseResponse)
async def update_knowledge_entry(
    entry_id: int,
    req: KnowledgeUpdate,
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """更新知识条目 (按business_area路由)"""
    KnModel = BUSINESS_KNOWLEDGE_MAP.get(business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
    stmt = select(KnModel).where(KnModel.id == entry_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    update_data = req.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        if hasattr(entry, key):
            setattr(entry, key, value)

    await db.commit()
    return BaseResponse(data={"id": entry.id, "knowledge_code": entry.knowledge_code})


@router.delete("/entries/{entry_id}", response_model=BaseResponse)
async def delete_knowledge_entry(
    entry_id: int,
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """软删除知识条目 (按business_area路由)"""
    KnModel = BUSINESS_KNOWLEDGE_MAP.get(business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
    stmt = select(KnModel).where(KnModel.id == entry_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="知识条目不存在")

    entry.status = "offline"
    await db.commit()
    return BaseResponse(data={"id": entry_id, "status": "offline"})


# ============================================
# Brands
# ============================================

@router.get("/brands", response_model=BaseResponse)
async def get_brands(
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """获取品牌列表"""
    stmt = select(BrandInfo).where(
        BrandInfo.business_area == business_area,
        BrandInfo.is_active == True,
    ).order_by(BrandInfo.priority)
    result = await db.execute(stmt)
    brands = result.scalars().all()

    items = [
        BrandItem(id=b.id, brand_code=b.brand_code, brand_name=b.brand_name, short_name=b.short_name)
        for b in brands
    ]
    return BaseResponse(data=[i.model_dump() for i in items])


# ============================================
# Categories
# ============================================

@router.get("/categories", response_model=BaseResponse)
async def get_categories(
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """获取分类树 (按business_area路由)"""
    KnModel = BUSINESS_KNOWLEDGE_MAP.get(business_area, BUSINESS_KNOWLEDGE_MAP["dashcam"])
    cat_l2_col = getattr(KnModel, "category_l2", None)
    cat_l1_col = getattr(KnModel, "category_l1", None) or getattr(KnModel, "category", None)

    if cat_l2_col is not None and cat_l1_col is not None:
        stmt = select(cat_l1_col, cat_l2_col, func.count(KnModel.id)).where(
            KnModel.status == "published"
        ).group_by(cat_l1_col, cat_l2_col)
    elif cat_l1_col is not None:
        stmt = select(cat_l1_col, func.count(KnModel.id)).where(
            KnModel.status == "published"
        ).group_by(cat_l1_col)
    else:
        return BaseResponse(data={})

    result = await db.execute(stmt)
    rows = result.all()

    tree = {}
    for row in rows:
        l1 = row[0] or "未分类"
        l2 = row[1] if len(row) > 2 else ""
        cnt = row[-1]
        if l1 not in tree:
            tree[l1] = []
        tree[l1].append({"name": l2, "count": cnt})

    return BaseResponse(data=tree)


# ============================================
# Import / Export
# ============================================

@router.post("/import", response_model=BaseResponse)
async def import_knowledge(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Excel导入知识库 (管理后台)"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx/.xls 文件")

    # TODO: 完整导入逻辑 (调用 scripts/import_kb.py 的导入器)
    return BaseResponse(data=ImportResult(
        total_rows=0,
        imported=0,
        skipped=0,
    ).model_dump())


@router.get("/export", response_model=BaseResponse)
async def export_knowledge(
    business_area: str = "dashcam",
    db: AsyncSession = Depends(get_db),
):
    """导出知识库Excel"""
    # TODO: 导出逻辑
    return BaseResponse(data={"message": "导出功能开发中"})
