# 知识答案预润色脚本
# 用法: python scripts/build_polished_answers.py [--force]
# 遍历所有已发布知识, 调大模型润色标准答案, 存入 polished_answer 字段
# 运行时查询直接读 polished_answer, 无需实时调大模型

import sys
import os
import asyncio

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import select
from app.core.database import get_session_factory
from app.models import KnowledgeAnswer
from app.services.llm_service import get_llm


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="知识答案预润色")
    parser.add_argument("--force", action="store_true", help="强制重算所有(包括已有polished_answer的)")
    parser.add_argument("--limit", type=int, default=0, help="只处理前N条(0=全部, 调试用)")
    args = parser.parse_args()

    print("🤖 加载大模型...")
    llm = get_llm()

    async with get_session_factory()() as db:
        stmt = select(KnowledgeAnswer).where(
            KnowledgeAnswer.status == "published",
            KnowledgeAnswer.business_area == "dashcam",
        )
        if not args.force:
            stmt = stmt.where(KnowledgeAnswer.polished_answer.is_(None))
        if args.limit > 0:
            stmt = stmt.limit(args.limit)

        result = await db.execute(stmt)
        knowledges = result.scalars().all()

        if not knowledges:
            print("✅ 没有需要润色的知识 (全部已处理)")
            return

        total = len(knowledges)
        print(f"\n📝 开始润色 {total} 条知识...")
        print(f"   预计耗时: 约 {total * 3} 秒\n")

        success = 0
        failed = 0
        for i, k in enumerate(knowledges, 1):
            try:
                polished = await llm.polish(k.standard_question, k.standard_answer)
                if polished and polished.strip():
                    k.polished_answer = polished
                    success += 1
                    status = "OK"
                else:
                    # 润色返回空, 用原文兜底
                    k.polished_answer = k.standard_answer
                    success += 1
                    status = "EMPTY→原文"
            except Exception as e:
                failed += 1
                status = f"FAIL: {e}"
                # 失败也用原文兜底, 保证运行时有内容
                k.polished_answer = k.standard_answer

            q_short = (k.standard_question or "")[:25]
            print(f"  [{i}/{total}] {k.knowledge_code} {q_short}... -> {status}")

            # 每10条提交一次, 避免长事务
            if i % 10 == 0:
                await db.commit()
                print(f"  --- 已提交 {i}/{total} ---")

        await db.commit()

    print(f"\n✅ 预润色完成!")
    print(f"   成功: {success} 条")
    print(f"   失败(回退原文): {failed} 条")
    print(f"   总计: {total} 条")
    print(f"\n💡 运行时查询将直接读 polished_answer, 无需实时调大模型")


if __name__ == "__main__":
    asyncio.run(main())
