# LangGraph 工作流状态定义
# 全局状态贯穿7个节点的完整生命周期

from typing import TypedDict, Optional, List, Dict, Any, Annotated
from langgraph.graph.message import add_messages


class SlotItem(TypedDict, total=False):
    """槽位项 - 用于渐进式收集用户信息"""
    field: str                          # 字段名: vin/terminal_id/sim_iccid/plate_number/brand
    display: str                        # 显示名: 车架号/终端号/SIM卡号/车牌号/品牌
    type: str                           # 类型: string/int
    value: Optional[str]                # 当前值
    collected: bool                     # 是否已收集
    collect_prompt: str                 # 收集提示语
    retry_count: int                    # 重试次数


class TransferDecision(TypedDict, total=False):
    """转人工决策结果"""
    should_transfer: bool
    reason_type: str                    # consecutive_fail/keyword/user_request/out_of_scope/risk
    reason: str
    priority: str                       # low/normal/high/urgent


class WorkflowState(TypedDict, total=False):
    """LangGraph 工作流全局状态"""

    # ============================================
    # 输入
    # ============================================
    query: str                          # 用户原始消息
    session_id: str                     # 会话UUID
    user_id: str                        # 用户ID (openid)
    business_area: str                  # 业务领域: dashcam/wifi/data/refueling
    channel: str                        # 渠道: miniprogram
    entry_point: str                    # 入口: 1_module/2_assistant/3_personal
    message_type: str                   # 消息类型: text/image/voice
    media_url: Optional[str]            # 媒体URL

    # ============================================
    # 多轮对话
    # ============================================
    messages: Annotated[list, add_messages]  # LangGraph 消息历史
    dialogue_round: int                 # 当前对话轮次
    consecutive_fail_count: int         # 连续未解决轮次
    collected_slots: Dict[str, Any]     # 已收集槽位 {vin: "LFW...", brand: "极目"}
    pending_slots: List[SlotItem]       # 待收集槽位列表

    # ============================================
    # 节点1: 预处理
    # ============================================
    cleaned_query: Optional[str]        # 清洗后的问题

    # ============================================
    # 节点2: 意图识别+问题改写
    # ============================================
    intent_type: str                    # knowledge_query/live_query/transfer_request/greeting/unknown
    intent_sub_type: Optional[str]      # 子类型
    rewritten_query: Optional[str]      # 改写后的问题
    intent_confidence: float            # 意图置信度 0.0-1.0

    # ============================================
    # 节点3: 知识库检索
    # ============================================
    matched_knowledge_ids: List[int]    # 匹配到的知识ID列表
    matched_knowledge_scores: List[float]  # 匹配分数
    knowledge_retrieval_method: str     # exact/keyword/vector/llm

    # ============================================
    # 节点4: 查询类型判断+条件收集
    # ============================================
    is_live_query: bool                 # 是否为实时数据库查询
    query_type_code: Optional[str]      # 查询类型编码 (QRY001-QRY013)
    required_slots: List[SlotItem]      # 所需槽位
    slots_collected: bool               # 槽位是否收集完成
    ask_slot_prompt: Optional[str]      # 询问槽位的提示语

    # ============================================
    # 节点5: 数据库查询
    # ============================================
    query_result: Optional[List[Dict[str, Any]]]  # 查询结果
    query_result_count: int             # 结果数量
    query_success: bool                 # 查询是否成功
    query_error: Optional[str]          # 查询错误信息

    # ============================================
    # 节点6: 回复生成
    # ============================================
    final_response: Optional[str]       # 最终回复
    response_type: str                  # knowledge_answer/query_result/ask_slot/transfer/greeting/fallback
    response_attachments: List[Dict]    # 附件 [{type, url, name}]
    follow_up_questions: List[str]      # 追问建议

    # ============================================
    # 节点7: 转人工判断
    # ============================================
    should_transfer: bool               # 是否需要转人工
    transfer_reason_type: Optional[str] # 转人工原因类型
    transfer_reason: Optional[str]      # 转人工原因
    transfer_summary: Optional[str]     # 完整对话上下文(给人工客服, 不做摘要)
    transfer_ticket_id: Optional[str]   # 工单ID
    transfer_priority: Optional[str]    # 工单优先级
    evaluation_prompt: Optional[str]    # 评价引导语

    # ============================================
    # 运行时
    # ============================================
    error: Optional[str]                # 错误信息
    metadata: Dict[str, Any]            # 扩展元数据
