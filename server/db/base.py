"""
数据库连接引擎 + 基础声明
"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from pgvector.sqlalchemy import Vector
import os


# 数据库 URL 构建
def get_database_url() -> str:
    """从环境变量构建数据库连接 URL"""
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "kefu")
    user = os.getenv("POSTGRES_USER", "kefu")
    pwd = os.getenv("POSTGRES_PASSWORD", "kefu_secret_change_me")
    return f"postgresql+asyncpg://{user}:{pwd}@{host}:{port}/{db}"


# 异步引擎
engine = create_async_engine(
    get_database_url(),
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
)

# 会话工厂
async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


async def init_db():
    """初始化数据库表（仅开发环境）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """获取数据库会话 (FastAPI 依赖注入)"""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ===== 懒加载 Embedding 模型 =====
_embedding_model = None

def get_embedding_model():
    """获取 sentence-transformers 模型（单例）"""
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        # 中文优选模型
        model_name = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
        _embedding_model = SentenceTransformer(model_name)
    return _embedding_model


def compute_embedding(text: str) -> list:
    """计算文本向量"""
    model = get_embedding_model()
    return model.encode(text, normalize_embeddings=True).tolist()


def compute_embeddings(texts: list[str]) -> list[list]:
    """批量计算文本向量"""
    model = get_embedding_model()
    embeddings = model.encode(texts, normalize_embeddings=True)
    return embeddings.tolist()
