# AI客服Agent 核心配置
import os
from pathlib import Path
from typing import Optional, Literal
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """应用配置中心"""

    # ============================================
    # 应用
    # ============================================
    APP_NAME: str = "AI-Customer-Service-Agent"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True
    SECRET_KEY: str = "change-me"

    # 项目根目录
    PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent

    # ============================================
    # MySQL
    # ============================================
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_USER: str = "root"
    MYSQL_PASSWORD: str = ""
    MYSQL_DATABASE: str = "kefu_agent"
    MYSQL_POOL_SIZE: int = 20
    MYSQL_POOL_RECYCLE: int = 3600

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+aiomysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    @property
    def DATABASE_URL_SYNC(self) -> str:
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}"
            f"@{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
        )

    # ============================================
    # Redis
    # ============================================
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0
    REDIS_SESSION_TTL: int = 86400

    # ============================================
    # LLM
    # ============================================
    # local  = 本地 Ollama (无需 API_KEY)
    # doubao = 火山方舟/豆包 (OpenAI 兼容, 需 LLM_API_KEY + LLM_MODEL=ep-xxx)
    # mock   = 规则兜底, 不依赖任何大模型
    LLM_PROVIDER: Literal["local", "doubao", "mock"] = "local"
    LLM_BASE_URL: str = "http://localhost:11434/v1"
    LLM_API_KEY: str = ""  # doubao 用; local 留空
    LLM_MODEL: str = "qwen2.5:7b"  # doubao 填推理接入点 ID, 如 ep-20240xxxxxx-xxxxx
    LLM_TEMPERATURE: float = 0.3
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT: int = 30

    # 备用LLM (保留兼容, 一般不用)
    BACKUP_LLM_PROVIDER: str = "doubao"
    BACKUP_LLM_BASE_URL: str = ""
    BACKUP_LLM_API_KEY: str = ""
    BACKUP_LLM_MODEL: str = ""

    # ============================================
    # 向量化
    # ============================================
    # provider=volcengine 用火山方舟 Embedding API (复用 LLM_API_KEY)
    # provider=local 用本地 sentence-transformers (需可访问 huggingface)
    EMBEDDING_PROVIDER: str = "volcengine"
    EMBEDDING_MODEL: str = "doubao-embedding-text-240715"
    EMBEDDING_DEVICE: str = "cpu"
    # 火山方舟 embedding 接口地址 (一般与 LLM_BASE_URL 同源)
    EMBEDDING_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"

    # ============================================
    # 七鱼客服
    # ============================================
    QIYU_ENABLED: bool = False
    QIYU_BASE_URL: str = ""
    QIYU_APP_KEY: str = ""
    QIYU_APP_SECRET: str = ""

    # ============================================
    # 业务配置
    # ============================================
    BUSINESS_HOURS_START: str = "09:00"
    BUSINESS_HOURS_END: str = "18:00"
    MAX_CONSECUTIVE_FAIL: int = 3
    SESSION_TIMEOUT_MINUTES: int = 30
    MAX_SLOT_RETRY: int = 2

    # 回复润色: 大模型对知识库答案做受限润色(只调格式/语气, 不改内容)
    ENABLE_POLISH: bool = True

    # ============================================
    # 运营平台接口 (实时查询设备信息)
    # ============================================
    # 默认线上地址; 内网测试容器可用环境变量覆盖为
    # http://172.29.30.157:32706/tob/openapi/business/batchVehicleInfo
    PLATFORM_API_URL: str = "https://dr.smartlink.com.cn/drapp/api/operate/tob/openapi/business/batchVehicleInfo"
    PLATFORM_API_TIMEOUT: int = 15

    # ============================================
    # CORS
    # ============================================
    CORS_ORIGINS: list[str] = ["*"]

    # ============================================
    # 知识库文件路径
    # ============================================
    @property
    def KB_EXCEL_PATH(self) -> Path:
        """行车记录仪知识库Excel路径

        PROJECT_ROOT 为 backend/ 目录, 知识库位于:
        实习/kefu-agent/记录仪知识库/xxx.xlsx
        即从 backend/ 上溯两级到 实习/, 再进入 kefu-agent/
        """
        return self.PROJECT_ROOT / ".." / ".." / "kefu-agent" / "记录仪知识库" / "行车记录仪Agent知识库_更新版618.xlsx"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# 全局单例
settings = Settings()
