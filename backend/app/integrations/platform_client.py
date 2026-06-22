# 运营平台数据对接
# 用于查询运营平台数据 (36万行设备的实时数据)

import httpx
from typing import Optional, Dict, Any, List
from app.core.config import settings


class PlatformClient:
    """运营平台API客户端

    用途:
    - 通过VIN/终端号/SIM查询设备信息
    - 查询在线状态、服务商、套餐等
    - 当本地 operational_device 表数据不足时, 回源到运营平台

    注意: 36万行数据用于精确查询, 不直接给大模型
    """

    def __init__(self):
        self.base_url = ""  # 运营平台API地址
        self.timeout = 10

    async def query_device_by_vin(self, vin: str) -> Optional[Dict[str, Any]]:
        """通过VIN查询设备"""
        # TODO: 对接运营平台真实API
        # 当前由本地 operational_device 表替代
        return None

    async def query_device_by_terminal(self, terminal_id: str) -> Optional[Dict[str, Any]]:
        """通过终端号查询设备"""
        return None

    async def query_online_status(self, vin: str) -> Optional[Dict[str, Any]]:
        """查询在线状态"""
        return None

    async def query_service_expiry(self, vin: str) -> Optional[Dict[str, Any]]:
        """查询服务到期时间"""
        return None

    async def batch_query(self, vins: List[str]) -> List[Dict[str, Any]]:
        """批量查询"""
        return []


# 全局单例
platform_client = PlatformClient()
