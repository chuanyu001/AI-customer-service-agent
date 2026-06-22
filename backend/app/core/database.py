# MySQL 异步数据库连接管理
# 引擎与工厂均为惰性创建, 避免在未安装驱动时阻断模型定义的导入
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from .config import settings


# ORM 基类 (独立于连接, 可在任何环境导入)
class Base(DeclarativeBase):
    pass


# 惰性创建的引擎与会话工厂
_engine = None
async_session_factory: Optional[async_sessionmaker] = None


def _ensure_engine():
    """惰性创建异步引擎与会话工厂 (首次访问数据库时触发)"""
    global _engine, async_session_factory
    if _engine is None:
        _engine = create_async_engine(
            settings.DATABASE_URL,
            echo=settings.DEBUG,
            pool_size=settings.MYSQL_POOL_SIZE,
            pool_recycle=settings.MYSQL_POOL_RECYCLE,
            pool_pre_ping=True,
        )
        async_session_factory = async_sessionmaker(
            _engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _engine


def get_engine():
    """获取异步引擎 (惰性)"""
    return _ensure_engine()


def get_session_factory() -> async_sessionmaker:
    """获取会话工厂 (惰性)"""
    _ensure_engine()
    return async_session_factory


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入: 获取数据库会话"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库: 创建所有表"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """关闭数据库连接"""
    global _engine, async_session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        async_session_factory = None
