# LangGraph 工作流编排
# 7节点 + 条件路由的 Agent 主工作流

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from .state import WorkflowState
from ..nodes.preprocess import preprocess_node
from ..nodes.intent_recognition import intent_recognition_node
from ..nodes.knowledge_retrieval import knowledge_retrieval_node
from ..nodes.query_judgment import query_judgment_node
from ..nodes.database_query import database_query_node
from ..nodes.response_generation import response_generation_node
from ..nodes.human_transfer import human_transfer_node


# ============================================
# 条件路由函数
# ============================================

def route_after_intent(state: WorkflowState) -> str:
    """意图识别后的路由决策"""
    intent = state.get("intent_type", "unknown")

    routing_map = {
        "transfer_request": "human_transfer",
        "greeting": "response_generation",
        "live_query": "query_judgment",
        "knowledge_query": "knowledge_retrieval",
        "unknown": "response_generation",  # 兜底回复
    }
    return routing_map.get(intent, "response_generation")


def route_after_knowledge_retrieval(state: WorkflowState) -> str:
    """知识库检索后的路由: 匹配度低→尝试查询判断"""
    scores = state.get("matched_knowledge_scores", [])
    if not scores or (max(scores) if scores else 0) < 0.3:
        # 知识库匹配度低, 检查是否为数据库查询意图
        return "query_judgment"
    return "response_generation"


def route_after_query_judgment(state: WorkflowState) -> str:
    """查询类型判断后的路由"""
    if state.get("is_live_query") and state.get("slots_collected"):
        return "database_query"
    # 槽位未收集 → 生成追问回复
    return "response_generation"


def route_after_response(state: WorkflowState) -> str:
    """回复生成后的路由: 是否需要转人工"""
    if state.get("should_transfer"):
        return "human_transfer"
    return END


# ============================================
# 创建工作流
# ============================================

def create_workflow() -> StateGraph:
    """创建主工作流图

    路由逻辑:
    ┌─────────────────────────────────────────────────────────────┐
    │  preprocess → intent_recognition                            │
    │                    ├── knowledge_query → knowledge_retrieval │
    │                    │       ├── 匹配成功 → response_gen        │
    │                    │       └── 匹配低 → query_judgment       │
    │                    ├── live_query → query_judgment           │
    │                    │       ├── 槽位完成 → database_query      │
    │                    │       └── 槽位不足 → response_gen        │
    │                    ├── transfer_request → human_transfer     │
    │                    ├── greeting → response_gen               │
    │                    └── unknown → response_gen                │
    │                                                              │
    │  database_query → response_gen → [转人工?] → END            │
    │                                         └── human_transfer   │
    └─────────────────────────────────────────────────────────────┘
    """
    workflow = StateGraph(WorkflowState)

    # 添加7个节点
    workflow.add_node("preprocess", preprocess_node)
    workflow.add_node("intent_recognition", intent_recognition_node)
    workflow.add_node("knowledge_retrieval", knowledge_retrieval_node)
    workflow.add_node("query_judgment", query_judgment_node)
    workflow.add_node("database_query", database_query_node)
    workflow.add_node("response_generation", response_generation_node)
    workflow.add_node("human_transfer", human_transfer_node)

    # 入口
    workflow.set_entry_point("preprocess")

    # preprocess → intent_recognition
    workflow.add_edge("preprocess", "intent_recognition")

    # intent_recognition → 条件路由
    workflow.add_conditional_edges(
        "intent_recognition",
        route_after_intent,
        {
            "knowledge_retrieval": "knowledge_retrieval",
            "query_judgment": "query_judgment",
            "response_generation": "response_generation",
            "human_transfer": "human_transfer",
        }
    )

    # knowledge_retrieval → 条件路由
    workflow.add_conditional_edges(
        "knowledge_retrieval",
        route_after_knowledge_retrieval,
        {
            "query_judgment": "query_judgment",
            "response_generation": "response_generation",
        }
    )

    # query_judgment → 条件路由
    workflow.add_conditional_edges(
        "query_judgment",
        route_after_query_judgment,
        {
            "database_query": "database_query",
            "response_generation": "response_generation",
        }
    )

    # database_query → response_generation
    workflow.add_edge("database_query", "response_generation")

    # response_generation → 条件路由 (转人工判断)
    workflow.add_conditional_edges(
        "response_generation",
        route_after_response,
        {
            "human_transfer": "human_transfer",
            END: END,
        }
    )

    # human_transfer → END
    workflow.add_edge("human_transfer", END)

    # 编译 (带 MemorySaver 用于多轮对话状态持久化)
    memory = MemorySaver()
    return workflow.compile(checkpointer=memory)


# 全局工作流实例
agent_workflow = create_workflow()
