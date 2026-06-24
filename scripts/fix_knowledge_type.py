# 修正知识类型: 以实际category_l2归纳5大类, 更新字典 + 回填category_l1
# 用法: python scripts/fix_knowledge_type.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select, update
from app.core.database import get_session_factory
from app.models import DashcamKnowledge, DataDictionary

# category_l2 → 一级分类 映射
CATEGORY_MAPPING = {
    # 故障排查
    "4G离线排查方法": "故障排查",
    "4G在线不定位排查": "故障排查",
    "不定位时屏幕显示": "故障排查",
    "视频通道测试方法": "故障排查",
    "定位天线识别": "故障排查",
    # 设备信息
    "厂家代码": "设备信息", "省市ID": "设备信息", "3C代码": "设备信息",
    "终端型号": "设备信息", "厂家电话": "设备信息", "原车司机卡": "设备信息",
    "插入IC卡后设备响应": "设备信息", "查询SIM/ID方法": "设备信息",
    "设备密码是多少？": "设备信息",
    "咨询北斗是4G,还是2G。": "设备信息",
    "咨询设备是不是单北斗": "设备信息",
    "设备现在是不是单北斗": "设备信息",
    # 操作指引
    "按键重启方法": "操作指引", "SIM卡拔插方法": "操作指引",
    "灾备视频导出方法": "操作指引", "背光延时设置方法": "操作指引",
    "如何提取记录仪视频": "操作指引", "如何录入司机卡的驾驶员信息": "操作指引",
    "记录仪面板钥匙找不到怎么办？": "操作指引",
    "设备支不支持换SIM卡使用？": "操作指引",
    # 驾驶监控
    "驾驶记录查询方法": "驾驶监控", "超时驾驶记录查询方法": "驾驶监控",
    "超时驾驶预警参数": "驾驶监控", "超速驾驶预警参数": "驾驶监控",
    "如何提取设备的行驶轨迹": "驾驶监控",
    "北斗不定位了，怎么提取车辆行驶轨迹": "驾驶监控",
    "北斗如何打印小票，是否具备打印机功能": "驾驶监控",
    "北斗设备的安装证明在哪里。": "驾驶监控",
    # 通用业务
    "如何调试新车货运": "通用业务", "新车调试的价格是多少？": "通用业务",
    "我要上牧运通": "通用业务", "设备怎么续费？": "通用业务",
    "车辆出事故了，换车头了，换设备了，怎么办？": "通用业务",
    "咨询设备能不能紧急开通上线": "通用业务",
    "原车行车记录仪设备能否拆卸，拆掉了是否会锁车": "通用业务",
    "设备如何连接第三方平台看视频。": "通用业务",
    "SIM卡卡号占用了怎么办？": "通用业务",
}

# 一级分类 → 字典编码
DICT_CODES = {
    "故障排查": "fault_troubleshooting",
    "设备信息": "device_info",
    "操作指引": "operation_guide",
    "驾驶监控": "driving_monitor",
    "通用业务": "general_business",
}


async def main():
    print("🔧 修正知识类型...\n")
    async with get_session_factory()() as db:
        # 1. 更新字典: 删除旧的5个knowledge_type
        old = (await db.execute(
            select(DataDictionary).where(DataDictionary.dict_type == "knowledge_type")
        )).scalars().all()
        for o in old:
            await db.delete(o)
        await db.commit()
        print(f"  删除旧字典 {len(old)} 条")

        # 插入新的5个
        for i, (cn, code) in enumerate(DICT_CODES.items(), 1):
            db.add(DataDictionary(
                dict_type="knowledge_type", dict_code=code,
                dict_value=cn, display_order=i, is_active=True,
            ))
        await db.commit()
        print(f"  插入新字典 {len(DICT_CODES)} 条: {list(DICT_CODES.keys())}")

        # 2. 回填 dashcam_knowledge.category_l1
        rows = (await db.execute(select(DashcamKnowledge))).scalars().all()
        updated = 0
        unmapped = []
        for r in rows:
            l1 = CATEGORY_MAPPING.get(r.category_l2)
            if l1:
                r.category_l1 = l1
                updated += 1
            else:
                unmapped.append((r.knowledge_code, r.category_l2))

        await db.commit()

    print(f"\n  回填 category_l1: {updated}/{len(rows)} 条")
    if unmapped:
        print(f"  ⚠️ 未映射 {len(unmapped)} 条:")
        for code, l2 in unmapped:
            print(f"    {code}: {l2}")

    # 验证
    print("\n🔍 验证:")
    async with get_session_factory()() as db:
        for code, cn in DICT_CODES.items():
            cnt = (await db.execute(
                select(DashcamKnowledge).where(DashcamKnowledge.category_l1 == cn)
            )).scalars().all()
            print(f"  {cn}({code}): {len(cnt)} 条")

    print("\n✅ 完成")


if __name__ == "__main__":
    asyncio.run(main())
