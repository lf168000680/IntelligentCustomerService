"""
数据库 ORM 模型
"""
import uuid
from datetime import datetime, date
from typing import Optional, List

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean,
    DateTime, Date, ForeignKey, JSON, Enum as SAEnum,
    Index, UniqueConstraint, text
)
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import relationship, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .base import Base


def gen_uuid():
    return str(uuid.uuid4())


def now():
    return datetime.now()


# ============================================================
# 会话与消息
# ============================================================

class Conversation(Base):
    """会话记录"""
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    platform: Mapped[str] = mapped_column(String(20), index=True)       # taobao / douyin
    shop_id: Mapped[str] = mapped_column(String(100), index=True)
    user_id: Mapped[str] = mapped_column(String(200), index=True)       # 平台用户ID
    user_name: Mapped[Optional[str]] = mapped_column(String(200))

    # 对话数据
    messages: Mapped[dict] = mapped_column(JSON, default=list)          # [{role, content, time, source}]
    turn_count: Mapped[int] = mapped_column(Integer, default=0)

    # 分类
    intent: Mapped[Optional[str]] = mapped_column(String(50))
    sentiment: Mapped[Optional[str]] = mapped_column(String(20))        # positive/neutral/negative

    # 处理状态
    resolution_status: Mapped[str] = mapped_column(
        String(30), default="pending", index=True
    )  # pending | ai_resolved | escalated | human_takeover | closed

    satisfaction: Mapped[Optional[int]] = mapped_column(Integer)          # 1-5 客户满意度
    knowledge_hits: Mapped[Optional[list]] = mapped_column(JSON)         # 命中的知识条目 ID

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    # 关联
    user_profile: Mapped[Optional["UserProfile"]] = relationship(
        back_populates="conversations", foreign_keys="UserProfile.conversation_id"
    )


# ============================================================
# 用户画像
# ============================================================

class UserProfile(Base):
    """用户画像"""
    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    user_id: Mapped[str] = mapped_column(String(200))                    # 平台用户ID
    user_name: Mapped[Optional[str]] = mapped_column(String(200))

    # 画像数据
    tags: Mapped[Optional[list]] = mapped_column(JSON)                   # ["价格敏感", "老客户", "爱退货"]
    order_count: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[float] = mapped_column(Float, default=0.0)
    preferences: Mapped[Optional[dict]] = mapped_column(JSON)            # {style, size, color, ...}

    # 最近活动
    last_seen: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_conversation_id: Mapped[Optional[str]] = mapped_column(String(36))
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("conversations.id"))

    # 备注
    notes: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

    # 关联
    conversations = relationship("Conversation", back_populates="user_profile", foreign_keys=[conversation_id])

    __table_args__ = (
        UniqueConstraint("platform", "user_id", name="uq_platform_user"),
    )


# ============================================================
# 知识库
# ============================================================

class KnowledgeItem(Base):
    """知识库条目"""
    __tablename__ = "knowledge_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON)

    # 来源追踪
    source: Mapped[str] = mapped_column(
        String(30), default="manual", index=True
    )  # manual | auto_learned | product_sync | seed

    source_conversation_id: Mapped[Optional[str]] = mapped_column(String(36))

    # 质量指标
    confidence: Mapped[float] = mapped_column(Float, default=1.0)       # 自动学习的置信度
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)

    # 向量嵌入 ID (pgvector 外联)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(36))

    # 状态
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    # active | pending_review (自动学习待审核) | archived | rejected

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


class KnowledgeEmbedding(Base):
    """知识库向量索引"""
    __tablename__ = "knowledge_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    knowledge_id: Mapped[Optional[str]] = mapped_column(String(36), ForeignKey("knowledge_items.id"))
    content: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(20), default="qa")  # qa | product | policy | conversation

    # 向量 (768 维 for bge-small-zh)
    embedding: Mapped[list] = mapped_column(Vector(768))

    # 元数据
    extra_meta: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    # 索引
    __table_args__ = (
        Index("idx_embedding_vector", "embedding", postgresql_using="ivfflat", postgresql_with={"lists": 100}),
    )


class ConversationEmbedding(Base):
    """对话向量索引"""
    __tablename__ = "conversation_embeddings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"))
    content: Mapped[str] = mapped_column(Text)

    embedding: Mapped[list] = mapped_column(Vector(768))
    extra_meta: Mapped[Optional[dict]] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


# ============================================================
# 知识审核队列
# ============================================================

class KnowledgeReview(Base):
    """自动学习审核队列"""
    __tablename__ = "knowledge_reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    source_conversation_ids: Mapped[Optional[list]] = mapped_column(JSON)
    supporting_count: Mapped[int] = mapped_column(Integer, default=1)   # 支持这个QA的对话数

    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    # pending | approved | rejected | modified

    reviewer_note: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)


# ============================================================
# 知识缺口
# ============================================================

class KnowledgeGap(Base):
    """知识缺口记录"""
    __tablename__ = "knowledge_gaps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    raw_question: Mapped[str] = mapped_column(Text)
    normalized_question: Mapped[Optional[str]] = mapped_column(Text)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    suggested_category: Mapped[Optional[str]] = mapped_column(String(100))

    # 最近的对话样例
    sample_conversation_ids: Mapped[Optional[list]] = mapped_column(JSON)

    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    # open | acknowledged | resolved

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ============================================================
# 商品快照
# ============================================================

class Product(Base):
    """商品信息快照"""
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    platform_product_id: Mapped[str] = mapped_column(String(200))

    title: Mapped[str] = mapped_column(String(500))
    price: Mapped[Optional[float]] = mapped_column(Float)
    stock: Mapped[Optional[int]] = mapped_column(Integer, default=0)
    specs: Mapped[Optional[dict]] = mapped_column(JSON)                # {颜色: [...], 尺码: [...]}
    images: Mapped[Optional[list]] = mapped_column(JSON)
    shipping_info: Mapped[Optional[dict]] = mapped_column(JSON)        # {发货地, 快递, 时效}
    description: Mapped[Optional[str]] = mapped_column(Text)

    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        UniqueConstraint("platform", "platform_product_id", name="uq_platform_product"),
    )


# ============================================================
# AI 模型配置存储
# ============================================================

class LLMProviderRecord(Base):
    """AI 模型配置 (持久化到数据库, GUI 可编辑, 支持自定义厂商和API中转站)"""
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100))
    provider: Mapped[str] = mapped_column(String(50))         # anthropic | openai | openai_compat | custom
    model_id: Mapped[str] = mapped_column(String(500))        # 支持自定义模型名
    api_key: Mapped[Optional[str]] = mapped_column(Text)      # 加密存储
    api_base: Mapped[Optional[str]] = mapped_column(Text)     # 自定义Endpoint (中转站用)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=4096)
    weight: Mapped[int] = mapped_column(Integer, default=100)
    tags: Mapped[Optional[list]] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    headers: Mapped[Optional[dict]] = mapped_column(JSON)     # 自定义HTTP头 (中转站认证)
    extra_config: Mapped[Optional[dict]] = mapped_column(JSON) # 扩展配置 (timeout等)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ============================================================
# 人设配置存储
# ============================================================

class PersonaRecord(Base):
    """人设文档存储"""
    __tablename__ = "personas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    shop_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # 文档内容 (也映射到 config/personas/ 目录)
    files: Mapped[dict] = mapped_column(JSON, default=dict)
    # { "SOUL.md": "...", "STYLE.md": "...", "SKILL.md": "...", "MEMORY.md": "...", "RULES.md": "..." }

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)


# ============================================================
# 统计报表
# ============================================================

class DailyStats(Base):
    """每日运营统计"""
    __tablename__ = "daily_stats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    stat_date: Mapped[date] = mapped_column(Date, index=True)
    shop_id: Mapped[str] = mapped_column(String(100))

    total_conversations: Mapped[int] = mapped_column(Integer, default=0)
    total_messages: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_time_seconds: Mapped[float] = mapped_column(Float, default=0)
    satisfaction_rate: Mapped[float] = mapped_column(Float, default=0)
    ai_resolved_rate: Mapped[float] = mapped_column(Float, default=0)
    escalation_rate: Mapped[float] = mapped_column(Float, default=0)

    top_intents: Mapped[Optional[dict]] = mapped_column(JSON)
    top_issues: Mapped[Optional[list]] = mapped_column(JSON)
    model_usage: Mapped[Optional[dict]] = mapped_column(JSON)          # 各模型调用统计

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

    __table_args__ = (
        UniqueConstraint("stat_date", "shop_id", name="uq_daily_stats"),
    )


# ============================================================
# 告警记录
# ============================================================

class AlertRecord(Base):
    """告警记录"""
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    level: Mapped[str] = mapped_column(String(20), default="info")    # info | warning | critical
    type: Mapped[str] = mapped_column(String(50))                      # login_expired | browser_crash | llm_error | ...
    message: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
