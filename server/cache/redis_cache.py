"""
L2 Redis 缓存 — 跨进程共享
"""
import json
import os
from typing import Optional, Any

from loguru import logger


class RedisCache:
    """
    Redis 缓存层

    特性:
    - 跨进程/跨实例共享
    - 支持 JSON 序列化
    - 原子操作
    - 发布/订阅失效通知
    """

    def __init__(self, redis_url: str = None, prefix: str = "kefu:cache:"):
        self._prefix = prefix
        self._redis = None
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    async def connect(self):
        """连接 Redis"""
        try:
            import redis.asyncio as aioredis
            self._redis = await aioredis.from_url(self._redis_url, decode_responses=True)
            await self._redis.ping()
            logger.info(f"Redis cache connected: {self._redis_url}")
        except ImportError:
            logger.warning("redis-py not installed, Redis cache disabled")
        except Exception as e:
            logger.warning(f"Redis connection failed: {e}, cache disabled")
            self._redis = None

    async def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if not self._redis:
            return None

        try:
            raw = await self._redis.get(self._prefix + key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.debug(f"Redis get error: {e}")
        return None

    async def set(self, key: str, value: Any, ttl: int = 300):
        """设置缓存"""
        if not self._redis:
            return

        try:
            await self._redis.setex(
                self._prefix + key,
                ttl,
                json.dumps(value, ensure_ascii=False, default=str),
            )
        except Exception as e:
            logger.debug(f"Redis set error: {e}")

    async def delete(self, key: str):
        """删除缓存"""
        if not self._redis:
            return

        try:
            await self._redis.delete(self._prefix + key)
        except Exception:
            pass

    async def delete_pattern(self, pattern: str):
        """按模式删除 (如 'kefu:cache:reply:*')"""
        if not self._redis:
            return

        try:
            cursor = 0
            full_pattern = self._prefix + pattern
            while True:
                cursor, keys = await self._redis.scan(cursor, match=full_pattern, count=100)
                if keys:
                    await self._redis.delete(*keys)
                if cursor == 0:
                    break
        except Exception:
            pass

    async def publish_invalidate(self, channel: str, message: str = "invalidate"):
        """发布缓存失效通知 (跨实例同步)"""
        if not self._redis:
            return

        try:
            await self._redis.publish(f"kefu:invalidate:{channel}", message)
        except Exception:
            pass

    async def subscribe_invalidate(self, channel: str, callback):
        """订阅缓存失效通知"""
        if not self._redis:
            return

        try:
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(f"kefu:invalidate:{channel}")
            # 在后台任务中监听
            import asyncio
            asyncio.create_task(self._listen(pubsub, callback))
        except Exception:
            pass

    async def _listen(self, pubsub, callback):
        while True:
            try:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=30)
                if message:
                    await callback(message)
            except Exception:
                await __import__('asyncio').sleep(1)

    async def close(self):
        """关闭连接"""
        if self._redis:
            await self._redis.close()

    @property
    def available(self) -> bool:
        return self._redis is not None
