# 种子数据脚本
# 用法: python scripts/seed_data.py
# 导入系统配置、数据字典、FAQ卡片等初始数据

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import get_session_factory
from app.models import SystemConfig, DataDictionary, FAQCard


SEED_CONFIGS = [
    # 业务配置
    {"key": "business_hours_start", "value": "09:00", "type": "string", "desc": "工作时间开始"},
    {"key": "business_hours_end", "value": "18:00", "type": "string", "desc": "工作时间结束"},
    {"key": "max_consecutive_fail", "value": "3", "type": "int", "desc": "最大连续失败轮次"},
    {"key": "session_timeout_minutes", "value": "30", "type": "int", "desc": "会话超时时间(分钟)"},
    {"key": "max_slot_retry", "value": "2", "type": "int", "desc": "槽位收集最大重试次数"},
    {"key": "ai_resolution_target", "value": "0.7", "type": "float", "desc": "AI解决率目标"},
    {"key": "transfer_rate_target", "value": "0.3", "type": "float", "desc": "转人工率目标"},
    {"key": "satisfaction_target", "value": "0.9", "type": "float", "desc": "满意度目标"},
    # 系统配置
    {"key": "welcome_message", "value": "您好! 我是AI客服助手, 请问有什么可以帮您的?", "type": "string", "desc": "欢迎语"},
    {"key": "transfer_message", "value": "正在为您转接人工客服, 请稍候...", "type": "string", "desc": "转人工提示语"},
    {"key": "off_hours_message", "value": "当前为非工作时间, 请描述您的问题并留下联系方式, 我们将在工作时间尽快回复您。", "type": "string", "desc": "非工作时间提示语"},
    {"key": "fallback_message_1", "value": "抱歉, 我暂时无法理解您的问题。请尝试用更简单的方式描述, 或选择转人工客服。", "type": "string", "desc": "兜底回复(第1次)"},
    {"key": "fallback_message_2", "value": "我仍然无法准确理解您的问题。建议您转人工客服获取帮助, 或者尝试换个方式描述您遇到的问题。", "type": "string", "desc": "兜底回复(第2次)"},
]

SEED_DICTIONARIES = [
    # 业务领域
    {"type": "business_area", "code": "dashcam", "value": "行车记录仪", "order": 1},
    {"type": "business_area", "code": "wifi", "value": "WiFi", "order": 2},
    {"type": "business_area", "code": "data", "value": "流量", "order": 3},
    {"type": "business_area", "code": "refueling", "value": "加油", "order": 4},
    # 知识类型
    {"type": "knowledge_type", "code": "fault_troubleshooting", "value": "故障排查", "order": 1},
    {"type": "knowledge_type", "code": "device_info", "value": "设备信息", "order": 2},
    {"type": "knowledge_type", "code": "operation_guide", "value": "操作指引", "order": 3},
    {"type": "knowledge_type", "code": "driving_monitor", "value": "驾驶监控", "order": 4},
    {"type": "knowledge_type", "code": "general_knowledge", "value": "通用知识", "order": 5},
    # 会话状态
    {"type": "conversation_status", "code": "active", "value": "活跃中", "order": 1},
    {"type": "conversation_status", "code": "transferred", "value": "已转人工", "order": 2},
    {"type": "conversation_status", "code": "resolved", "value": "已解决", "order": 3},
    {"type": "conversation_status", "code": "closed", "value": "已关闭", "order": 4},
    # 转人工原因
    {"type": "transfer_reason", "code": "consecutive_fail", "value": "连续多轮未解决", "order": 1},
    {"type": "transfer_reason", "code": "keyword", "value": "关键词触发", "order": 2},
    {"type": "transfer_reason", "code": "user_request", "value": "用户要求转人工", "order": 3},
    {"type": "transfer_reason", "code": "out_of_scope", "value": "超出AI服务范围", "order": 4},
    {"type": "transfer_reason", "code": "risk", "value": "高风险问题", "order": 5},
    # 工单优先级
    {"type": "ticket_priority", "code": "low", "value": "低", "order": 1},
    {"type": "ticket_priority", "code": "normal", "value": "普通", "order": 2},
    {"type": "ticket_priority", "code": "high", "value": "高", "order": 3},
    {"type": "ticket_priority", "code": "urgent", "value": "紧急", "order": 4},
    # 优化样本类型
    {"type": "sample_type", "code": "no_match", "value": "未匹配到知识", "order": 1},
    {"type": "sample_type", "code": "low_confidence", "value": "低置信度匹配", "order": 2},
    {"type": "sample_type", "code": "bad_answer", "value": "答非所问", "order": 3},
    {"type": "sample_type", "code": "user_complaint", "value": "用户投诉", "order": 4},
]

# FAQ卡片种子数据 (从知识库高频问题中选取)
SEED_FAQ_CARDS = [
    {"code": "FAQ_DASHCAM_001", "area": "dashcam", "title": "设备离线了怎么办?", "category": "故障排查", "order": 1},
    {"code": "FAQ_DASHCAM_002", "area": "dashcam", "title": "如何查询SIM卡号和终端号?", "category": "设备信息", "order": 2},
    {"code": "FAQ_DASHCAM_003", "area": "dashcam", "title": "设备不定位怎么处理?", "category": "故障排查", "order": 3},
    {"code": "FAQ_DASHCAM_004", "area": "dashcam", "title": "如何导出记录仪视频?", "category": "操作指引", "order": 4},
    {"code": "FAQ_DASHCAM_005", "area": "dashcam", "title": "如何查看驾驶记录?", "category": "驾驶监控", "order": 5},
    {"code": "FAQ_DASHCAM_006", "area": "dashcam", "title": "设备怎么重启?", "category": "操作指引", "order": 6},
    {"code": "FAQ_DASHCAM_007", "area": "dashcam", "title": "SIM卡怎么拔插?", "category": "操作指引", "order": 7},
    {"code": "FAQ_DASHCAM_008", "area": "dashcam", "title": "设备密码是多少?", "category": "设备信息", "order": 8},
    {"code": "FAQ_DASHCAM_009", "area": "dashcam", "title": "设备怎么续费?", "category": "通用知识", "order": 9},
    {"code": "FAQ_DASHCAM_010", "area": "dashcam", "title": "超速/疲劳驾驶预警参数是什么?", "category": "驾驶监控", "order": 10},
]


async def seed_data():
    """导入种子数据"""
    async with get_session_factory()() as db:
        count = 0

        # 系统配置
        print("📥 导入系统配置...")
        for cfg in SEED_CONFIGS:
            existing = await db.get(SystemConfig, cfg["key"])
            if not existing:
                db.add(SystemConfig(
                    config_key=cfg["key"],
                    config_value=cfg["value"],
                    config_type=cfg["type"],
                    description=cfg["desc"],
                ))
                count += 1
        print(f"  ✅ 系统配置: {count} 条")

        # 数据字典
        dict_count = 0
        print("📥 导入数据字典...")
        for item in SEED_DICTIONARIES:
            db.add(DataDictionary(
                dict_type=item["type"],
                dict_code=item["code"],
                dict_value=item["value"],
                display_order=item["order"],
            ))
            dict_count += 1
        print(f"  ✅ 数据字典: {dict_count} 条")

        # FAQ卡片
        faq_count = 0
        print("📥 导入FAQ卡片...")
        for card in SEED_FAQ_CARDS:
            db.add(FAQCard(
                card_code=card["code"],
                business_area=card["area"],
                title=card["title"],
                category=card["category"],
                display_order=card["order"],
                is_active=True,
            ))
            faq_count += 1
        print(f"  ✅ FAQ卡片: {faq_count} 条")

        await db.commit()
        print(f"\n✅ 种子数据导入完成! 共 {count + dict_count + faq_count} 条 (已提交)")


if __name__ == "__main__":
    asyncio.run(seed_data())
