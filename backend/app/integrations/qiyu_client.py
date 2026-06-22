# 七鱼客服对接
# 转人工工单 → 七鱼客服系统

import httpx
from typing import Optional, Dict, Any
from app.core.config import settings


class QiyuClient:
    """七鱼客服API客户端

    用途:
    - 将转人工工单同步到七鱼系统
    - 创建七鱼会话
    - 查询客服在线状态
    """

    def __init__(self):
        self.enabled = settings.QIYU_ENABLED
        self.base_url = settings.QIYU_BASE_URL
        self.app_key = settings.QIYU_APP_KEY
        self.app_secret = settings.QIYU_APP_SECRET

    async def create_session(
        self,
        ticket_id: str,
        user_id: str,
        summary: str,
        collected_info: Dict[str, Any],
        reason_type: str,
        priority: str = "normal",
    ) -> Optional[str]:
        """创建七鱼会话 → 返回七鱼会话ID

        Args:
            ticket_id: 本系统工单ID
            user_id: 用户ID
            summary: AI对话摘要
            collected_info: 已收集的业务信息
            reason_type: 转人工原因类型
            priority: 优先级

        Returns:
            七鱼会话ID (失败返回None)
        """
        if not self.enabled:
            return None

        try:
            payload = {
                "ticketId": ticket_id,
                "userId": user_id,
                "summary": summary,
                "collectedInfo": collected_info,
                "reasonType": reason_type,
                "priority": priority,
                "source": "ai_agent",
            }

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/api/v1/sessions",
                    json=payload,
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                data = response.json()
                return data.get("sessionId")

        except Exception as e:
            print(f"⚠️ 七鱼会话创建失败: {e}")
            return None

    async def get_customer_service_status(self) -> Dict[str, Any]:
        """查询客服在线状态"""
        if not self.enabled:
            return {"online": False, "message": "七鱼对接未启用"}

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{self.base_url}/api/v1/status",
                    headers=self._auth_headers(),
                )
                response.raise_for_status()
                return response.json()
        except Exception as e:
            return {"online": False, "message": str(e)}

    def _auth_headers(self) -> Dict[str, str]:
        """生成认证头"""
        # TODO: 根据七鱼实际认证方式实现
        return {
            "X-App-Key": self.app_key,
            "X-App-Secret": self.app_secret,
            "Content-Type": "application/json",
        }


# 全局单例
qiyu_client = QiyuClient()
