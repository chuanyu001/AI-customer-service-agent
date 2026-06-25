# 知识向量预计算脚本
# 用法:
#   python scripts/build_embeddings.py
#   python scripts/build_embeddings.py --business-area dashcam --force

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import close_db, get_session_factory, init_db
from app.services.embedding_service import embedding_service


async def main():
    parser = argparse.ArgumentParser(description="四业务知识库向量预计算")
    parser.add_argument("--force", action="store_true", help="强制重算所有向量")
    parser.add_argument(
        "--business-area",
        choices=["dashcam", "wifi", "data", "refueling"],
        default=None,
        help="只构建指定业务; 默认构建全部业务",
    )
    parser.add_argument("--skip-smoke", action="store_true", help="跳过构建后的检索冒烟测试")
    args = parser.parse_args()

    print(f"Embedding provider: {embedding_service.model_name}")
    print(f"Business area: {args.business_area or 'all'}")

    await init_db()

    factory = get_session_factory()
    async with factory() as db:
        stats = await embedding_service.build_all_embeddings(
            db,
            force=args.force,
            business_area=args.business_area,
        )

    print("向量预计算完成")
    print(f"  总知识数: {stats['total']}")
    print(f"  新算/更新: {stats['computed']}")
    print(f"  跳过未变更: {stats['skipped']}")

    factory2 = get_session_factory()
    async with factory2() as db:
        loaded = await embedding_service.load_to_memory(db)
    print(f"  内存加载: {loaded} 条向量")

    if not args.skip_smoke and loaded:
        area = args.business_area or "dashcam"
        query = {
            "dashcam": "设备离线怎么办",
            "wifi": "WiFi套餐怎么买",
            "data": "基础流量怎么用",
            "refueling": "折扣加油怎么开票",
        }.get(area, "设备离线怎么办")
        print(f"冒烟测试 [{area}]: {query}")
        for kid, score in await embedding_service.search(query, business_area=area, top_k=3):
            print(f"  knowledge_id={kid} score={score:.4f}")

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
