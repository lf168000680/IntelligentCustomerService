"""
消息总线 — 统一消息路由
多平台消息汇聚、会话管理、消息去重、优先级调度
"""
import json
import hashlib
import asyncio
from typing import Dict, Optional, Any, Callable, Awaitable
from datetime import datetime

from loguru import logger


class MessageBus:
    """
    消息总线

    职责:
    - 接收来自各平台适配器的消息
    - 路由到 AI 引擎处理
    - 会话亲和性 (同一用户路由到同一处理)
    - 消息去重
    - 超时监控
    """

    def __init__(self, engine=None, db_factory=None):
        self.engine = engine                      # CoreEngine 实例
        self.db_factory = db_factory              # DB session factory

        # 活跃会话
        self.active_sessions: Dict[str, Dict] = {}

        # 消息去重缓存 (msg_id → hash)
        self.recent_messages: Dict[str, float] = {}

        # 处理锁 (防止同一用户并发处理)
        self.user_locks: Dict[str, asyncio.Lock] = {}

        # 回调
        self.on_reply: Optional[Callable[[Dict], Awaitable[None]]] = None

    async def route(self, raw_message: Dict[str, Any]) -> Optional[Dict]:
        """
        路由一条原始消息

        raw_message:
        {
            "platform": "taobao" | "douyin",
            "shop_id": "...",
            "user_id": "平台用户ID",
            "user_name": "客户昵称",
            "content": "消息文本",
            "msg_id": "平台消息ID (用于去重)",
            "timestamp": "ISO时间",
            "product": {...} or None   # 当前浏览商品
        }

        Returns:
            {"reply": "...", "escalate": False, ...} or None
        """
        msg_id = raw_message.get("msg_id", "")
        content = raw_message.get("content", "").strip()
        user_id = raw_message.get("user_id", "")

        if not content or not user_id:
            return None

        # ── 去重 ──
        content_hash = hashlib.md5(f"{msg_id}:{content}".encode()).hexdigest()
        if content_hash in self.recent_messages:
            logger.debug(f"Duplicate message: {msg_id}")
            return None
        self.recent_messages[content_hash] = datetime.now().timestamp()

        # 清理过期去重缓存
        now = datetime.now().timestamp()
        self.recent_messages = {
            k: v for k, v in self.recent_messages.items()
            if now - v < 300  # 5分钟过期
        }

        # ── 获取/创建会话上下文 ──
        session_key = f"{raw_message.get('platform', '')}:{raw_message.get('shop_id', '')}:{user_id}"
        session = self.active_sessions.get(session_key)

        if not session:
            session = await self._load_or_create_session(raw_message)
            self.active_sessions[session_key] = session

        # ── 获取用户锁 ──
        if user_id not in self.user_locks:
            self.user_locks[user_id] = asyncio.Lock()

        # ── 处理消息 ──
        async with self.user_locks[user_id]:
            try:
                result = await self._process_message(raw_message, session)
            except Exception as e:
                logger.error(f"Message processing error: {e}")
                result = {
                    "reply": "稍等哦亲亲，系统有点卡，马上就好～ 😊",
                    "intent": "error",
                    "escalate": False,
                    "metadata": {"error": str(e)},
                }

        # ── 更新会话状态 ──
        session["history"].append({"role": "user", "content": content, "time": raw_message.get("timestamp")})
        if result and result.get("reply"):
            session["history"].append({"role": "assistant", "content": result["reply"],
                                        "time": datetime.now().isoformat()})
        session["last_active"] = now

        # 限制历史长度
        if len(session["history"]) > 100:
            session["history"] = session["history"][-100:]

        # ── 触发回复回调 ──
        if self.on_reply and result:
            try:
                await self.on_reply({
                    **raw_message,
                    "reply": result["reply"],
                    "escalate": result.get("escalate", False),
                    "metadata": result.get("metadata", {}),
                })
            except Exception as e:
                logger.error(f"Reply callback error: {e}")

        return result

    async def _process_message(self, raw: Dict, session: Dict) -> Optional[Dict]:
        """处理单条消息"""
        if not self.engine:
            logger.warning("No engine available, skipping message")
            return {"reply": "稍等下哦亲亲～我去叫人来看看 😊", "escalate": True}

        context = {
            "conversation_id": session.get("conversation_id"),
            "user_id": raw.get("user_id"),
            "user_name": raw.get("user_name"),
            "shop_id": raw.get("shop_id"),
            "platform": raw.get("platform"),
            "history": session.get("history", []),
            "user_profile": session.get("user_profile"),
            "product": raw.get("product"),
        }

        result = await self.engine.process(raw["content"], context)
        return result

    async def _load_or_create_session(self, raw: Dict) -> Dict:
        """加载或创建会话上下文"""
        session = {
            "conversation_id": None,
            "user_id": raw.get("user_id"),
            "user_name": raw.get("user_name"),
            "shop_id": raw.get("shop_id"),
            "platform": raw.get("platform"),
            "history": [],
            "user_profile": {},
            "last_active": datetime.now().timestamp(),
            "created_at": datetime.now().isoformat(),
        }

        # 从数据库加载历史
        if self.db_factory:
            try:
                async with self.db_factory() as db:
                    from sqlalchemy import select
                    from ..db.models import UserProfile, Conversation

                    # 加载用户画像
                    result = await db.execute(
                        select(UserProfile).where(
                            UserProfile.platform == raw.get("platform"),
                            UserProfile.user_id == raw.get("user_id"),
                        )
                    )
                    profile = result.scalar_one_or_none()
                    if profile:
                        session["user_profile"] = {
                            "tags": profile.tags or [],
                            "order_count": profile.order_count,
                            "total_spent": profile.total_spent,
                            "preferences": profile.preferences or {},
                        }

                    # 加载最近会话
                    result = await db.execute(
                        select(Conversation).where(
                            Conversation.platform == raw.get("platform"),
                            Conversation.user_id == raw.get("user_id"),
                        ).order_by(Conversation.created_at.desc()).limit(1)
                    )
                    conv = result.scalar_one_or_none()
                    if conv:
                        session["conversation_id"] = conv.id
                        session["history"] = conv.messages[-20:] if conv.messages else []
            except Exception as e:
                logger.warning(f"Failed to load session from DB: {e}")

        return session

    def get_session(self, user_id: str, platform: str = "", shop_id: str = "") -> Optional[Dict]:
        """获取活跃会话"""
        key = f"{platform}:{shop_id}:{user_id}"
        return self.active_sessions.get(key)

    def get_active_count(self) -> int:
        """活跃会话数"""
        return len(self.active_sessions)

    def cleanup_stale_sessions(self, max_age_seconds: int = 3600):
        """清理过期会话"""
        now = datetime.now().timestamp()
        stale_keys = [
            k for k, v in self.active_sessions.items()
            if now - v.get("last_active", 0) > max_age_seconds
        ]
        for k in stale_keys:
            del self.active_sessions[k]
        if stale_keys:
            logger.info(f"Cleaned up {len(stale_keys)} stale sessions")

    async def shutdown(self):
        """优雅关闭"""
        # 保存所有活跃会话到数据库
        if self.db_factory:
            try:
                async with self.db_factory() as db:
                    import uuid
                    from ..db.models import Conversation

                    for key, session in self.active_sessions.items():
                        if len(session.get("history", [])) < 2:
                            continue

                        conv = Conversation(
                            id=str(uuid.uuid4()),
                            platform=session.get("platform", "unknown"),
                            shop_id=session.get("shop_id", "default"),
                            user_id=session.get("user_id", ""),
                            user_name=session.get("user_name", ""),
                            messages=session.get("history", []),
                            turn_count=len([m for m in session.get("history", [])
                                            if m.get("role") == "user"]),
                            resolution_status="closed",
                        )
                        db.add(conv)
                    await db.commit()
                    logger.info(f"Saved {len(self.active_sessions)} sessions to DB")
            except Exception as e:
                logger.error(f"Failed to save sessions: {e}")

        self.active_sessions.clear()
        self.recent_messages.clear()
