# 知识向量预计算脚本
# 用法: python scripts/build_embeddings.py [--force]
# 把所有已发布知识编码成向量, 存入 knowledge_embedding 表

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.database import get_session_factory
from app.services.embedding_service import embedding_service


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="知识向量预计算")
    parser.add_argument("--force", action="store_true", help="强制重算所有向量")
    args = parser.parse_args()

    print(f"🧮 加载向量化模型: {embedding_service._model_name}")
    print("   (首次运行需下载模型, 约100MB, 请稍候...)")

    # 触发模型加载
    embedding_service._get_model()
    print("✅ 模型加载完成")

    async with get_session_factory()() as db:
        print("\n📥 预计算知识向量...")
        stats = await embedding_service.build_all_embeddings(db, force=args.force)

    print(f"\n✅ 向量预计算完成!")
    print(f"   总知识数: {stats['total']}")
    print(f"   新算/更新: {stats['computed']}")
    print(f"   跳过(未变更): {stats['skipped']}")

    # 顺便加载到内存验证
    async with get_session_factory()() as db:
        n = await embedding_service.load_to_memory(db)
    print(f"   内存加载: {n} 条向量")

    # 简单冒烟测试
    if n > 0:
        print("\n🧪 冒烟测试: '设备没法用了'")
        results = await embedding_service.search("设备没法用了", top_k=3)
        for kid, score in results:
            print(f"   knowledge_id={kid}  score={score:.4f}")


if __name__ == "__main__":
    asyncio.run(main())
