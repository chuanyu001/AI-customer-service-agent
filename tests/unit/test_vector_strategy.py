# 向量检索策略的纯函数测试

from app.api.chat import _should_route_live_query
from app.services.embedding_service import EmbeddingService


def test_live_query_routing_keeps_instructional_questions_in_knowledge_base():
    assert not _should_route_live_query("怎么查询SIM卡号", "QRY001")
    assert not _should_route_live_query("设备怎么续费", "QRY007")


def test_live_query_routing_detects_personal_device_queries():
    assert _should_route_live_query("帮我查一下SIM卡号", "QRY001")
    assert _should_route_live_query("我的服务什么时候到期", "QRY008")
    assert _should_route_live_query("我的车架号是 LFNAHUPMXT1E19383, 查一下设备号", "QRY002")


def test_embedding_source_text_uses_retrieval_fields_only():
    source = EmbeddingService.build_source_text(
        standard_question="设备离线怎么办",
        category="4G离线排查方法",
        manufacturer="极目",
        common_phrasings="设备不在线;记录仪离线",
        variants=["4G不在线怎么处理"],
        keywords=["离线", "4G"],
    )

    assert "设备离线怎么办" in source
    assert "4G离线排查方法" in source
    assert "极目" in source
    assert "4G不在线怎么处理" in source
    assert "离线" in source
    assert "请先检查" not in source
