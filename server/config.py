"""
统一配置管理
系统基础配置来自 .env，模型配置元数据来自 providers.yaml
API Key 存储在数据库中 (加密)，通过 GUI 管理，不写入环境变量
"""
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

import dotenv

# 加载 .env (仅系统级配置: 数据库、端口等)
ENV_FILE = Path(__file__).parent.parent / ".env"
if ENV_FILE.exists():
    dotenv.load_dotenv(ENV_FILE)

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class ModelConfig:
    """单个 LLM 模型配置 (API Key 从 DB 加载, 支持自定义厂商和中转站)"""
    name: str
    provider: str                           # 自由字符串: anthropic | openai | openai_compat | custom | ...
    model_id: str
    api_key: str = ""                       # 从 DB 解密获取
    api_base: Optional[str] = None          # 自定义 Endpoint (中转站/relay)
    temperature: float = 0.7
    max_tokens: int = 4096
    weight: int = 100
    enabled: bool = True
    tags: List[str] = field(default_factory=lambda: ["default"])
    headers: Optional[dict] = None          # 自定义 HTTP 头
    extra_config: Optional[dict] = None     # 扩展配置


@dataclass
class RoutingConfig:
    """路由配置"""
    scene_tags: Dict[str, List[str]] = field(default_factory=dict)
    fallback_order: List[str] = field(default_factory=list)
    max_retries: int = 3
    retry_delay_ms: int = 1000


@dataclass
class AppConfig:
    """全局应用配置"""
    # 数据库
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "kefu"
    postgres_user: str = "kefu"
    postgres_password: str = "kefu_secret_change_me"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # 服务
    server_host: str = "0.0.0.0"
    server_port: int = 8800
    gui_port: int = 8801
    debug: bool = False
    log_level: str = "INFO"

    # 模型元数据 (不含 API Key)
    model_templates: List[ModelConfig] = field(default_factory=list)
    models: List[ModelConfig] = field(default_factory=list)
    routing: RoutingConfig = field(default_factory=RoutingConfig)

    # 回复延迟 (秒)
    auto_reply_delay_min: int = 15
    auto_reply_delay_max: int = 60

    # 通知
    notify_webhook_url: Optional[str] = None
    notify_type: str = "telegram"

    @property
    def database_url(self) -> str:
        return (f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def database_url_sync(self) -> str:
        return (f"postgresql://{self.postgres_user}:{self.postgres_password}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")


def load_config() -> AppConfig:
    """加载基础配置 (不含模型 API Key，那由 DB 加载)"""
    config = AppConfig()

    # 从环境变量加载
    config.postgres_host = os.environ.get("POSTGRES_HOST", config.postgres_host)
    config.postgres_port = int(os.environ.get("POSTGRES_PORT", str(config.postgres_port)))
    config.postgres_db = os.environ.get("POSTGRES_DB", config.postgres_db)
    config.postgres_user = os.environ.get("POSTGRES_USER", config.postgres_user)
    config.postgres_password = os.environ.get("POSTGRES_PASSWORD", config.postgres_password)
    config.redis_url = os.environ.get("REDIS_URL", config.redis_url)
    config.server_host = os.environ.get("SERVER_HOST", config.server_host)
    config.server_port = int(os.environ.get("SERVER_PORT", str(config.server_port)))
    config.gui_port = int(os.environ.get("GUI_PORT", str(config.gui_port)))
    config.debug = os.environ.get("DEBUG", "").lower() == "true"
    config.log_level = os.environ.get("LOG_LEVEL", config.log_level)
    config.auto_reply_delay_min = int(os.environ.get("AUTO_REPLY_DELAY_MIN", str(config.auto_reply_delay_min)))
    config.auto_reply_delay_max = int(os.environ.get("AUTO_REPLY_DELAY_MAX", str(config.auto_reply_delay_max)))
    config.notify_webhook_url = os.environ.get("NOTIFY_WEBHOOK_URL")
    config.notify_type = os.environ.get("NOTIFY_TYPE", config.notify_type)

    # 加载 providers.yaml 元数据 (不含 API Key)
    providers_path = PROJECT_ROOT / "config" / "providers.yaml"
    if providers_path.exists():
        with open(providers_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # 模型元数据模板 (api_key 留空，从 DB 加载)
        for item in data.get("providers", []):
            item.setdefault("api_key", "")   # 确保字段存在，值从 DB 获取
            item.setdefault("api_base", None)
            config.model_templates.append(ModelConfig(**item))

        # 路由配置
        routing_data = data.get("routing", {})
        config.routing = RoutingConfig(**routing_data)

    return config


async def load_models_from_db(db_session) -> List[ModelConfig]:
    """
    从数据库加载模型配置 (含加密的 API Key)
    合并 yaml 元数据模板 + DB 中的 API Key

    逻辑:
    1. 读取 DB 中所有已保存的模型记录
    2. 用 DB 记录覆盖 yaml 模板中的同名模型 (以 DB 为准)
    3. 如果 yaml 中有新模型而 DB 中没有，自动插入 DB
    """
    from sqlalchemy import select
    from .crypto_utils import decrypt_api_key
    from .db.models import LLMProviderRecord

    # 查询 DB 中的模型记录
    result = await db_session.execute(
        select(LLMProviderRecord).order_by(LLMProviderRecord.name)
    )
    db_records = {r.name: r for r in result.scalars().all()}

    models = []

    for template in config.model_templates:
        db_record = db_records.pop(template.name, None)

        if db_record:
            # DB 中有记录 → 以 DB 为准
            api_key = decrypt_api_key(db_record.api_key or "")
            models.append(ModelConfig(
                name=db_record.name,
                provider=db_record.provider,
                model_id=db_record.model_id,
                api_key=api_key,
                api_base=db_record.api_base or template.api_base,
                temperature=db_record.temperature,
                max_tokens=db_record.max_tokens,
                weight=db_record.weight,
                enabled=db_record.enabled,
                tags=db_record.tags or template.tags,
                headers=db_record.headers or template.headers,
                extra_config=db_record.extra_config or template.extra_config,
            ))
        else:
            # DB 中无记录 → 用 yaml 模板 (api_key 为空，需用户在 GUI 中填写)
            models.append(template)

    # DB 中有但 yaml 中没有的模型 (用户在 GUI 中手动添加的)
    for name, record in db_records.items():
        api_key = decrypt_api_key(record.api_key or "")
        models.append(ModelConfig(
            name=record.name,
            provider=record.provider,
            model_id=record.model_id,
            api_key=api_key,
            api_base=record.api_base,
            temperature=record.temperature,
            max_tokens=record.max_tokens,
            weight=record.weight,
            enabled=record.enabled,
            tags=record.tags or ["default"],
            headers=record.headers,
            extra_config=record.extra_config,
        ))

    return models


async def seed_models_to_db(db_session):
    """首次启动时将 providers.yaml 模板导入数据库"""
    from sqlalchemy import select
    from .crypto_utils import encrypt_api_key
    from .db.models import LLMProviderRecord

    for template in config.model_templates:
        # 检查是否已存在
        result = await db_session.execute(
            select(LLMProviderRecord).where(LLMProviderRecord.name == template.name)
        )
        existing = result.scalar_one_or_none()

        if not existing:
            record = LLMProviderRecord(
                name=template.name,
                provider=template.provider,
                model_id=template.model_id,
                api_key="",  # 无 API Key，需用户在 GUI 中填写
                api_base=template.api_base,
                temperature=template.temperature,
                max_tokens=template.max_tokens,
                weight=template.weight,
                enabled=template.enabled,
                tags=template.tags,
                headers=template.headers,
                extra_config=template.extra_config,
            )
            db_session.add(record)

    await db_session.commit()


# 全局配置实例
config = load_config()
