# Redis 连接管理
# redis 依赖惰性导入, 避免在未安装时阻断应用启动
from typing import Optional
from .config import settings


# Redis连接 (惰性创建)
_redis = None


async def get_redis():
    """获取Redis连接 (懒加载)"""
    global _redis
    if _redis is None:
        import redis.asyncio as aioredis
        _redis = aioredis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            password=settings.REDIS_PASSWORD or None,
            db=settings.REDIS_DB,
            decode_responses=True,
        )
    return _redis


async def close_redis():
    """关闭Redis连接"""
    global _redis
    if _redis is not None:
        try:
            await _redis.close()
        except Exception:
            pass
        _redis = None


async def get_session_state(session_id: str) -> Optional[dict]:
    """从Redis获取会话状态"""
    import json
    try:
        r = await get_redis()
        data = await r.get(f"session:{session_id}")
        return json.loads(data) if data else None
    except Exception:
        return None


async def set_session_state(session_id: str, state: dict, ttl: int = None):
    """将会话状态写入Redis"""
    import json
    if ttl is None:
        ttl = settings.REDIS_SESSION_TTL
    try:
        r = await get_redis()
        await r.setex(f"session:{session_id}", ttl, json.dumps(state, default=str))
    except Exception:
        pass


async def delete_session_state(session_id: str):
    """删除会话状态"""
    try:
        r = await get_redis()
        await r.delete(f"session:{session_id}")
    except Exception:
        pass
