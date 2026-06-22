"""
Kefu - 智能电商客服系统
主入口
使用方式: 从项目根目录运行 python -m server.main
"""
import sys
import asyncio
from pathlib import Path

# 确保项目根目录在 path 中
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

# 配置日志
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="DEBUG",
)
logger.add(
    "logs/kefu_{time:YYYY-MM-DD}.log",
    rotation="10 MB",
    retention="30 days",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} - {message}",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# 使用相对导入, 避免与项目根目录的 config/ 冲突
from .config import config as app_config
from .llm.router import router as llm_router
from .engine.core import CoreEngine
from .engine.persona import get_persona
from .bus.message_bus import MessageBus
from .knowledge.learning_pipeline import KnowledgeLearningPipeline
from .adapters.session_manager import SessionManager
from .scheduler.jobs import JobScheduler
from .db.base import engine as db_engine, init_db


# ===== FastAPI 应用 =====

app = FastAPI(
    title="Kefu AI 客服系统",
    description="24H 无人值守智能电商客服",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===== 全局组件 =====

engine: CoreEngine = None
message_bus: MessageBus = None
knowledge_pipeline: KnowledgeLearningPipeline = None
session_manager: SessionManager = None
scheduler: JobScheduler = None


@app.on_event("startup")
async def startup():
    """应用启动"""
    global engine, message_bus, knowledge_pipeline, session_manager, scheduler

    logger.info("=" * 50)
    logger.info("Kefu AI 客服系统启动中...")
    logger.info("=" * 50)

    # 0. 确保所有模型已注册 (必须在 init_db 之前导入)
    from .db.models import (
        Conversation, UserProfile, KnowledgeItem, KnowledgeEmbedding,
        ConversationEmbedding, KnowledgeReview, KnowledgeGap, Product,
        LLMProviderRecord, PersonaRecord, DailyStats, AlertRecord,
    )

    # 1. 初始化数据库
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database init skipped (may be already initialized): {e}")

    # 2. 种子模型模板到数据库 (首次启动)
    try:
        from .db.base import async_session as _session
        async with _session() as db:
            from .config import seed_models_to_db
            await seed_models_to_db(db)
            logger.info("Model templates seeded to DB")
    except Exception as e:
        logger.warning(f"Model seed skipped: {e}")

    # 3. 从数据库加载模型 (含 API Key) 并注册到 Router
    try:
        from .db.base import async_session as _session2
        async with _session2() as db:
            from .config import load_models_from_db
            app_config.models = await load_models_from_db(db)
            logger.info(f"Loaded {len(app_config.models)} models from DB")
    except Exception as e:
        logger.warning(f"Failed to load models from DB: {e}")

    # 4. LLM Router
    llm_router.register_from_app_config()
    logger.info(f"LLM Router ready: {len(llm_router.all_entries)} providers")

    # 3. Persona
    persona = get_persona("default")
    logger.info(f"Persona loaded: {persona.persona_name}")

    # 5. Core Engine
    engine = CoreEngine(
        llm_router=llm_router,
        persona_name="default",
    )
    logger.info("Core Engine ready")

    # Initialize agent tools
    try:
        from .tools import init_tools
        from .db.base import async_session as _as_for_tools
        tool_registry = await init_tools(
            db_factory=_as_for_tools,
            llm_router=llm_router
        )
        logger.info(f"Agent tools initialized: {len(tool_registry.list_all())} tools")
    except Exception as e:
        logger.warning(f"Tool initialization skipped: {e}")

    # 5.5. 缓存系统初始化
    try:
        from .cache import cache_manager
        await cache_manager.connect()
        # 预热: 将知识库FAQ加载到缓存
        try:
            from .db.base import async_session as _sess
            from .db.models import KnowledgeItem
            from sqlalchemy import select
            async with _sess() as db:
                result = await db.execute(
                    select(KnowledgeItem).where(KnowledgeItem.status == "active").limit(50)
                )
                faqs = [{"question": r.question, "answer": r.answer} for r in result.scalars().all()]
                if faqs:
                    await cache_manager.warm_up(faqs)
        except Exception:
            pass
        logger.info(f"Cache system ready: L1={cache_manager.L1.size}, L3={cache_manager.L3.size}")
    except Exception as e:
        logger.warning(f"Cache initialization skipped: {e}")

    # 7. MCP 客户端 + 工具注册
    try:
        from .mcp import mcp_client
        mcp_results = await mcp_client.connect_all()
        mcp_connected = sum(1 for v in mcp_results.values() if v)
        # 将 MCP 工具注册到 Agent 工具系统
        await mcp_client.register_tools_to_agent()
        logger.info(f"MCP: {mcp_connected}/{len(mcp_results)} servers connected, tools registered")
    except Exception as e:
        logger.warning(f"MCP initialization skipped: {e}")

    # 8. Browser 适配器 (agent-browser 集成)
    try:
        from .browser import browser_adapter
        browser_adapter.mcp = mcp_client
        logger.info("Browser adapter ready (agent-browser via MCP)")
    except Exception as e:
        logger.warning(f"Browser adapter skipped: {e}")

    # 9. Message Bus
    message_bus = MessageBus(
        engine=engine,
        db_factory=None,  # 后续补充
    )
    logger.info("Message Bus ready")

    # 6. Knowledge Pipeline
    knowledge_pipeline = KnowledgeLearningPipeline(
        db_factory=None,  # 需要 DB session factory
        llm_router=llm_router,
        persona_builder=persona,
    )

    # 7. Session Manager
    session_manager = SessionManager()

    # 8. Scheduler
    scheduler = JobScheduler(
        message_bus=message_bus,
        session_manager=session_manager,
        knowledge_pipeline=knowledge_pipeline,
    )
    await scheduler.start()

    logger.info("=" * 50)
    logger.info("Kefu AI 客服系统已就绪!")
    logger.info(f"API: http://{app_config.server_host}:{app_config.server_port}")
    logger.info(f"Docs: http://{app_config.server_host}:{app_config.server_port}/docs")
    logger.info("=" * 50)


@app.on_event("shutdown")
async def shutdown():
    """应用关闭"""
    logger.info("Shutting down...")

    if scheduler:
        await scheduler.stop()

    if session_manager:
        await session_manager.stop_all()

    if message_bus:
        await message_bus.shutdown()

    if db_engine:
        await db_engine.dispose()

    # MCP 断开
    try:
        from .mcp import mcp_client
        await mcp_client.disconnect_all()
    except Exception:
        pass

    # 缓存关闭
    try:
        from .cache import cache_manager
        await cache_manager.close()
    except Exception:
        pass

    logger.info("Kefu shut down complete")


# ===== API 路由 =====

@app.get("/")
async def root():
    return {
        "service": "Kefu AI 客服系统",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_providers": llm_router.get_status() if llm_router else {},
        "message_bus": {
            "active_sessions": message_bus.get_active_count() if message_bus else 0,
        },
        "adapters": await session_manager.health_check() if session_manager else {},
    }


# 导入 API 路由
from .api.routes import chat, knowledge, persona, models, analytics, system, mcp, browser, cache

app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["Knowledge"])
app.include_router(persona.router, prefix="/api/persona", tags=["Persona"])
app.include_router(models.router, prefix="/api/models", tags=["Models"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(system.router, prefix="/api/system", tags=["System"])
app.include_router(mcp.router, prefix="/api/mcp", tags=["MCP"])
app.include_router(browser.router, prefix="/api/browser", tags=["Browser"])
app.include_router(cache.router, prefix="/api/cache", tags=["Cache"])


# ===== 主函数 =====

def main():
    uvicorn.run(
        "server.main:app",
        host=app_config.server_host,
        port=app_config.server_port,
        reload=app_config.debug,
        log_level=app_config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
