# 数据库初始化脚本
# 用法: python scripts/init_db.py
# 创建所有表 + 可选导入知识库

import sys
import os
import asyncio

# 将项目根目录加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.config import settings
from app.core.database import Base, get_engine, close_db
from app.models import *  # noqa: F401,F403 — 确保所有模型被注册


async def init_database():
    """创建所有数据库表"""
    print("正在创建所有数据库表...")
    await init_db_schema()
    await close_db()
    print("[OK] 数据库表创建完成!")


async def init_db_schema():
    """创建表结构"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables():
    """删除所有表 (危险操作, 仅开发环境)"""
    if settings.DEBUG:
        confirm = input("[WARN] 即将删除所有表! 输入 'yes' 确认: ")
        if confirm != "yes":
            print("已取消")
            return

        engine = get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await close_db()
        print("[OK] 所有表已删除")
    else:
        print("[FAIL] 非开发环境, 不允许删除表")


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="数据库初始化")
    parser.add_argument("--drop", action="store_true", help="先删除所有表再创建")
    args = parser.parse_args()

    if args.drop:
        await drop_all_tables()

    await init_database()


if __name__ == "__main__":
    asyncio.run(main())
