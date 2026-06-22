# Chat 相关 Pydantic 模型

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class ChatMessageRequest(BaseModel):
    """发送消息请求"""
    session_id: Optional[str] = Field(default=None, description="会话ID, 首次为空则创建新会话")
    user_id: Optional[str] = Field(default=None, description="用户ID (openid)")
    business_area: str = Field(default="dashcam", description="业务领域: dashcam/wifi/data/refueling")
    content: str = Field(..., min_length=1, max_length=2000, description="消息内容")
    content_type: str = Field(default="text", description="消息类型: text/image/voice")
    media_url: Optional[str] = Field(default=None, description="媒体URL")
    entry_point: Optional[str] = Field(default=None, description="入口: 1_module/2_assistant/3_personal")


class ChatMessageResponse(BaseModel):
    """消息响应"""
    session_id: str
    message_id: str
    seq: int
    role: str = "assistant"
    content: str
    content_type: str = "text"
    response_type: str = "fallback"
    knowledge_code: Optional[str] = None
    attachments: List[Dict[str, str]] = []
    follow_up_questions: List[str] = []
    should_transfer: bool = False
    need_more_info: bool = False
    ask_slot_prompt: Optional[str] = None
    evaluation_prompt: Optional[str] = None


class SessionCreateResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    welcome_message: str
    faq_cards: List[Dict[str, Any]] = []


class ConversationDetail(BaseModel):
    """会话详情"""
    session_id: str
    user_id: Optional[str]
    business_area: str
    status: str
    message_count: int
    ai_resolved: bool
    transfer_count: int
    started_at: Optional[str]
    ended_at: Optional[str]


class MessageDetail(BaseModel):
    """消息详情"""
    message_id: str
    seq: int
    role: str
    content: str
    content_type: str
    action: Optional[str]
    reply_type: Optional[str]
    knowledge_code: Optional[str]
    created_at: Optional[str]


class ConversationMessagesResponse(BaseModel):
    """会话消息列表"""
    conversation: ConversationDetail
    messages: List[MessageDetail]


class ImageUploadResponse(BaseModel):
    """图片上传响应"""
    media_url: str
    recognized_vin: Optional[str] = None
