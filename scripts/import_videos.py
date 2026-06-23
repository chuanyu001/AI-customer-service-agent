# 视频附件导入脚本
# 把5个操作视频的URL导入 knowledge_attachment 表, 关联到对应知识
# 用法: python scripts/import_videos.py

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select, delete
from app.core.database import get_session_factory
from app.models import KnowledgeAnswer, KnowledgeAttachment

# 视频 → 知识编号 映射
# URL用相对路径 /videos/文件名, 前端与后端同源访问
VIDEO_MAP = [
    {
        "knowledge_code": "KB0091",  # 极目拔插SIM卡
        "file_name": "极目设备拔插SIM卡操作视频",
        "file_url": "/videos/1.1极目--拔插SIM卡视频.mp4",
    },
    {
        "knowledge_code": "KB0093",  # 航天拔插SIM卡
        "file_name": "航天设备拔插SIM卡操作视频",
        "file_url": "/videos/2.1航天拔插SIM卡视频.mp4",
    },
    {
        "knowledge_code": "KB0094",  # 雅迅拔插SIM卡
        "file_name": "雅迅设备拔插SIM卡操作视频",
        "file_url": "/videos/3.1雅迅SIM卡拔插视频.mp4",
    },
    {
        "knowledge_code": "KB0087",  # 航天导出灾备视频
        "file_name": "航天设备导出灾备视频操作演示",
        "file_url": "/videos/2.3航天U盘提取灾备视频.mp4",
    },
    {
        "knowledge_code": "KB0088",  # 雅迅导出灾备视频
        "file_name": "雅迅设备导出灾备视频操作演示",
        "file_url": "/videos/3.3雅迅U盘提取灾备视频.mp4",
    },
]


async def main():
    print("🎬 导入视频附件到 knowledge_attachment 表...\n")
    async with get_session_factory()() as db:
        # 先清空旧的附件(避免重复)
        await db.execute(delete(KnowledgeAttachment))
        await db.flush()

        count = 0
        for item in VIDEO_MAP:
            # 查知识ID
            stmt = select(KnowledgeAnswer).where(KnowledgeAnswer.knowledge_code == item["knowledge_code"])
            result = await db.execute(stmt)
            knowledge = result.scalar_one_or_none()
            if not knowledge:
                print(f"  ⚠️ 知识 {item['knowledge_code']} 不存在, 跳过")
                continue

            db.add(KnowledgeAttachment(
                knowledge_id=knowledge.id,
                file_name=item["file_name"],
                file_type="video",
                file_url=item["file_url"],
                display_order=count,
            ))
            print(f"  ✅ {item['knowledge_code']} {knowledge.standard_question[:20]}... → {item['file_url']}")
            count += 1

        await db.commit()

    print(f"\n✅ 导入完成! 共 {count} 个视频附件")
    print(f"   访问地址示例: http://localhost:8001/videos/1.1极目--拔插SIM卡视频.mp4")


if __name__ == "__main__":
    asyncio.run(main())
