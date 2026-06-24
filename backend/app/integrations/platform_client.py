# 运营平台数据对接
# 通过 batchVehicleInfo 接口实时查询设备信息 (仅支持 VIN 查询)
# 返回字段已对齐 OperationalDevice 模型字段名, 下游 field_dictionary 映射/过滤可零改动复用

import logging
from typing import Optional, Dict, Any, List

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 接口原始字段 → OperationalDevice 字段名 (便于复用 field_dictionary 映射)
# 注意: 品牌字段(brand)目前接口尚未返回, 预留映射, 待接口提供后自动生效
_FIELD_MAP = {
    "vin": "vin",
    "carNumber": "plate_number",
    "recorderId": "terminal_id",
    "validDateEnd": "service_expiry",
    # 品牌字段预留 (接口暂未返回, 返回后此处映射即生效)
    "brand": "device_brand",
    "recorderBrand": "device_brand",
}


class PlatformClient:
    """运营平台 API 客户端

    用途:
    - 通过 VIN 查询设备信息 (车牌号 / 记录仪设备号 / 到期时间)
    - 仅支持 VIN 查询, 不直接给大模型 (结果经 field_dictionary 过滤后再用)

    注意: 接口无鉴权, 仅内网/专网可达, 本地开发可能连不上线上域名
          通过 PLATFORM_API_URL 环境变量切换内网测试地址
    """

    def __init__(self):
        self.base_url = settings.PLATFORM_API_URL
        self.timeout = settings.PLATFORM_API_TIMEOUT

    async def batch_query(self, vins: List[str]) -> List[Dict[str, Any]]:
        """批量按 VIN 查询设备

        POST {"vinList": [...]} → 返回映射后的 dict 列表
        每项字段: vin / plate_number / terminal_id / service_expiry
        异常或非 200 → 返回空列表 (不抛出, 由调用方走空结果/转人工)
        """
        if not vins:
            return []

        body = {"vinList": [v.strip().upper() for v in vins if v]}
        if not body["vinList"]:
            return []

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(self.base_url, json=body)
                resp.raise_for_status()
                obj = resp.json()
        except Exception as e:
            logger.warning("运营平台接口调用失败 url=%s err=%s", self.base_url, e)
            return []

        code = obj.get("code")
        if code != 200:
            logger.warning("运营平台接口返回非 200 code=%s body=%s", code, str(obj)[:300])
            return []

        data = obj.get("data") or []
        results = []
        for item in data:
            mapped = {}
            for raw_field, value in (item or {}).items():
                backend_field = _FIELD_MAP.get(raw_field)
                if backend_field and value is not None:
                    mapped[backend_field] = str(value)
            if mapped:
                results.append(mapped)
        return results

    async def query_device_by_vin(self, vin: str) -> Optional[Dict[str, Any]]:
        """通过 VIN 查询单个设备, 返回首条结果"""
        results = await self.batch_query([vin])
        return results[0] if results else None

    async def get_device_brand(self, vin: str) -> Optional[Dict[str, Any]]:
        """通过 VIN 查询设备品牌信息 (两级品牌识别用)

        Returns:
            {"brand": 品牌名(鱼快/航天/雅迅/启明/空), "terminal_id": 终端号}
            接口未返回品牌字段时 brand=None, 但 terminal_id 可能有值
            查询失败返回 None
        """
        device = await self.query_device_by_vin(vin)
        if not device:
            return None
        return {
            "brand": device.get("device_brand"),  # 接口暂未返回时为 None
            "terminal_id": device.get("terminal_id"),
        }


# 全局单例
platform_client = PlatformClient()
