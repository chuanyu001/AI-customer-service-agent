# 节点3: 知识库检索
# 三层检索 + 品牌感知 + 品牌降级

from typing import List, Optional
from ..graph.state import WorkflowState
from ..services.knowledge_service import knowledge_service
from ..services.brand_service import BrandIdentificationService

brand_service = BrandIdentificationService()


async def knowledge_retrieval_node(state: WorkflowState) -> WorkflowState:
    """知识库检索节点

    处理流程:
    1. 获取改写后的问题
    2. 尝试品牌识别 (从用户输入 + 已收集信息)
    3. 三层检索 (L1精确 → L2关键词 → L3向量)
    4. 品牌降级: 该品牌无知识 → 降级到通用知识
    """
    query = state.get("rewritten_query", state.get("query", ""))
    business_area = state.get("business_area", "dashcam")
    collected_slots = state.get("collected_slots", {})

    # ============================================
    # Step 1: 品牌识别
    # ============================================
    brand_id = collected_slots.get("brand_id")
    brand_name = collected_slots.get("brand")

    if not brand_id:
        # 尝试从用户输入快速提取品牌关键词
        keyword_result = await brand_service.identify_by_keyword(query)
        if keyword_result and keyword_result.confidence >= 0.8:
            brand_name = keyword_result.brand_name
            # 存储品牌信息到 collected_slots
            state["collected_slots"]["brand"] = brand_name

    # ============================================
    # Step 2: 三层检索 (品牌逻辑已在chat.py处理)
    # ============================================
    matched_ids, matched_scores, method = await knowledge_service.retrieve(
        db=None,  # 由调用方注入, 这里从state获取
        query=query,
        business_area=business_area,
        top_k=5,
    )

    # ============================================
    # Step 3: 更新状态
    # ============================================
    state["matched_knowledge_ids"] = matched_ids
    state["matched_knowledge_scores"] = matched_scores
    state["knowledge_retrieval_method"] = method

    # 如果知识库匹配度低, 标记为可能需要转人工
    if not matched_ids or (matched_scores and max(matched_scores) < 0.3):
        state["consecutive_fail_count"] = state.get("consecutive_fail_count", 0) + 1

    return state


async def knowledge_retrieval_with_db(state: WorkflowState, db) -> WorkflowState:
    """带数据库会话的知识库检索 (实际调用入口)"""
    query = state.get("rewritten_query", state.get("query", ""))
    business_area = state.get("business_area", "dashcam")
    collected_slots = state.get("collected_slots", {})

    # 品牌识别
    brand_id = collected_slots.get("brand_id")
    brand_name = collected_slots.get("brand")

    if not brand_id:
        keyword_result = await brand_service.identify_by_keyword(query)
        if keyword_result and keyword_result.confidence >= 0.8:
            brand_name = keyword_result.brand_name
            state["collected_slots"]["brand"] = brand_name

    # 三层检索 (品牌逻辑已在chat.py处理, 此处仅按business_area检索)
    matched_ids, matched_scores, method = await knowledge_service.retrieve(
        db=db,
        query=query,
        business_area=business_area,
        top_k=5,
    )

    state["matched_knowledge_ids"] = matched_ids
    state["matched_knowledge_scores"] = matched_scores
    state["knowledge_retrieval_method"] = method

    if not matched_ids or (matched_scores and max(matched_scores) < 0.3):
        state["consecutive_fail_count"] = state.get("consecutive_fail_count", 0) + 1

    return state
