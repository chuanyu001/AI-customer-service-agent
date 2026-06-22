# 工作流集成测试 (需运行中的服务)

import pytest
import httpx

API_BASE = "http://localhost:8000/api/v1"


@pytest.mark.asyncio
async def test_create_session():
    """测试创建会话"""
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{API_BASE}/chat/sessions?business_area=dashcam")
        assert res.status_code == 200
        data = res.json()
        assert data["code"] == 0
        assert "session_id" in data["data"]


@pytest.mark.asyncio
async def test_greeting_message():
    """测试问候语"""
    async with httpx.AsyncClient() as client:
        # 创建会话
        res = await client.post(f"{API_BASE}/chat/sessions?business_area=dashcam")
        session_id = res.json()["data"]["session_id"]

        # 发送问候
        res = await client.post(f"{API_BASE}/chat/message", json={
            "session_id": session_id,
            "business_area": "dashcam",
            "content": "你好",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["response_type"] == "greeting"


@pytest.mark.asyncio
async def test_transfer_keyword():
    """测试转人工关键词"""
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{API_BASE}/chat/sessions?business_area=dashcam")
        session_id = res.json()["data"]["session_id"]

        res = await client.post(f"{API_BASE}/chat/message", json={
            "session_id": session_id,
            "business_area": "dashcam",
            "content": "我要转人工",
        })
        data = res.json()["data"]
        assert data["should_transfer"] is True
        assert data["response_type"] == "transfer"


@pytest.mark.asyncio
async def test_knowledge_query():
    """测试知识库问答"""
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{API_BASE}/chat/sessions?business_area=dashcam")
        session_id = res.json()["data"]["session_id"]

        res = await client.post(f"{API_BASE}/chat/message", json={
            "session_id": session_id,
            "business_area": "dashcam",
            "content": "设备怎么重启",
        })
        data = res.json()["data"]
        assert data["content"]  # 应有回复内容


@pytest.mark.asyncio
async def test_health():
    """测试健康检查"""
    async with httpx.AsyncClient() as client:
        res = await client.get("http://localhost:8000/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
