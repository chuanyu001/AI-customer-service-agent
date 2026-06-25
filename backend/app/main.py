# FastAPI 应用入口

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from app.core.config import settings
from app.core.database import init_db, close_db
from app.core.redis_client import close_redis
from app.api import chat, knowledge, evaluation, admin
from app.services.embedding_service import embedding_service
from app.services.rule_service import load_keyword_rules, seed_default_keyword_rules

# 日志配置
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    logger.info("🚀 启动 AI客服Agent 服务...")
    logger.info(f"   LLM Provider: {settings.LLM_PROVIDER} ({settings.LLM_MODEL})")
    logger.info(f"   Database: {settings.MYSQL_HOST}:{settings.MYSQL_PORT}/{settings.MYSQL_DATABASE}")

    try:
        await init_db()
        logger.info("✅ 数据库初始化完成")
        seeded_rules, loaded_rules = await _load_keyword_rules()
        logger.info("✅ 规则关键词加载完成: %s 条, 新增默认规则 %s 条", loaded_rules, seeded_rules)
        loaded = await _load_embeddings()
        logger.info("✅ 知识向量缓存加载完成: %s 条", loaded)
    except Exception as e:
        logger.warning(f"⚠️ 数据库初始化失败 (可手动运行 scripts/init_db.py): {e}")

    yield

    # 关闭
    logger.info("👋 关闭服务...")
    await close_db()
    await close_redis()


# 创建应用
app = FastAPI(
    title=settings.APP_NAME,
    description="AI智能客服Agent — 覆盖行车记录仪/WiFi/流量/加油四大业务领域",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(chat.router, prefix="/api/v1")
app.include_router(knowledge.router, prefix="/api/v1")
app.include_router(evaluation.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")


async def _load_embeddings() -> int:
    """启动时加载已预计算向量; 加载失败不阻断服务."""
    try:
        from app.core.database import get_session_factory

        factory = get_session_factory()
        async with factory() as db:
            count = await embedding_service.load_to_memory(db)

        # 预热本地模型, 避免第一个用户请求等7秒+
        if settings.EMBEDDING_PROVIDER == "local" and count > 0:
            try:
                _ = embedding_service.encode("预热")
                logger.info("Embedding 模型预热完成")
            except Exception:
                pass

        return count
    except Exception as e:
        logger.warning("知识向量缓存加载失败, 将跳过向量检索: %s", e)
        return 0


async def _load_keyword_rules() -> tuple[int, int]:
    """启动时补齐并加载 keyword_rule; 加载失败时使用代码默认规则."""
    try:
        from app.core.database import get_session_factory

        factory = get_session_factory()
        async with factory() as db:
            seeded = await seed_default_keyword_rules(db)
            if seeded:
                await db.commit()
            loaded = await load_keyword_rules(db)
        return seeded, loaded
    except Exception as e:
        logger.warning("规则关键词加载失败, 将使用代码默认规则: %s", e)
        return 0, 0


# ============================================
# 前端静态页面托管 (H5 聊天页)
# ============================================
# 前端目录: 项目根/frontend/h5-chat/
# 访问 http://localhost:8000/ 即聊天页; http://localhost:8000/docs 为 API 文档
# index.html 中引用 css/style.css 与 js/*.js 为根相对路径, 故将子目录分别挂载
_FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "h5-chat"
if _FRONTEND_DIR.exists():
    _CSS_DIR = _FRONTEND_DIR / "css"
    _JS_DIR = _FRONTEND_DIR / "js"
    _VIDEOS_DIR = _FRONTEND_DIR / "videos"
    if _CSS_DIR.exists():
        app.mount("/css", StaticFiles(directory=str(_CSS_DIR)), name="css")
    if _JS_DIR.exists():
        app.mount("/js", StaticFiles(directory=str(_JS_DIR)), name="js")
    if _VIDEOS_DIR.exists():
        app.mount("/videos", StaticFiles(directory=str(_VIDEOS_DIR)), name="videos")
        logger.info(f"📁 视频目录已挂载: {_VIDEOS_DIR}")
    logger.info(f"📁 前端静态目录已挂载: {_FRONTEND_DIR}")


# ============================================
# 全局异常处理
# ============================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"未处理异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器内部错误: {str(exc)}",
            "data": None,
        },
    )


# ============================================
# 根路由 — 返回 H5 聊天页
# ============================================

from fastapi.responses import FileResponse

_INDEX_HTML = _FRONTEND_DIR / "index.html"


@app.get("/")
async def root():
    """根路由: 返回 H5 聊天页 (存在时), 否则返回服务信息"""
    if _INDEX_HTML.exists():
        return FileResponse(str(_INDEX_HTML))
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok", "service": settings.APP_NAME, "version": settings.APP_VERSION}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
