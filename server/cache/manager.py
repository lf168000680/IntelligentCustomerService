"""
CacheManager — 多级缓存统一调度

流程:
用户消息 → L1(内存精确) → L2(Redis精确) → L3(语义相似度) → LLM调用
                ↓命中              ↓命中             ↓命中
             直接返回           直接返回          直接返回
"""
import time
import hashlib
from typing import Optional, Dict, Any, Tuple

from loguru import logger

from .memory_cache import MemoryCache
from .redis_cache import RedisCache
from .semantic_cache import SemanticCache
from .hit_tracker import HitTracker


class CacheManager:
    """
    三级缓存管理器

    L1 — 内存精确匹配 (0.1ms)
         key = md5(message+intent+persona)
         适合: 完全相同的消息

    L2 — Redis 精确匹配 (1-5ms)
         key = md5(message+intent+persona)
         适合: 跨进程/跨重启的相同消息

    L3 — Embedding 语义匹配 (10-50ms)
         余弦相似度 > 0.85 即命中
         适合: "什么时候发货" ≈ "多久能发出"
    """

    def __init__(self,
                 l1_max_size: int = 10000,
                 l1_ttl: float = 600,
                 l3_max_size: int = 5000,
                 l3_threshold: float = 0.85,
                 l3_ttl: float = 3600,
                 l3_extended_ttl: float = 86400):
        self.L1 = MemoryCache(max_size=l1_max_size, default_ttl=l1_ttl)
        self.L2 = RedisCache()
        self.L3 = SemanticCache(
            max_size=l3_max_size,
            similarity_threshold=l3_threshold,
            default_ttl=l3_ttl,
            extended_ttl=l3_extended_ttl,
        )
        self.tracker = HitTracker()

        self._embedding_model = None
        self._enabled = True

    async def connect(self):
        """连接 Redis"""
        await self.L2.connect()

    async def close(self):
        """关闭连接"""
        await self.L2.close()

    # ── 核心 API ──────────────────────────────────

    async def get_or_compute(
        self,
        message: str,
        intent: str = "",
        persona_name: str = "default",
        compute_func=None,  # async (message, intent) -> str
        ttl: int = None,
    ) -> Tuple[str, dict]:
        """
        获取缓存或计算新回复

        Args:
            message: 客户消息
            intent: 意图分类
            persona_name: 人设名称 (不同人设不同缓存)
            compute_func: 缓存未命中时的计算函数
            ttl: 自定义 TTL

        Returns:
            (回复文本, 元数据)
        """
        if not self._enabled:
            reply = await compute_func(message, intent)
            return reply, {"source": "no_cache"}

        cache_key = self._make_key(message, intent, persona_name)
        meta = {}

        # ── L1: 内存精确匹配 ──
        t0 = time.time()
        cached = self.L1.get(cache_key)
        if cached is not None:
            latency = (time.time() - t0) * 1000
            self.tracker.record_hit("L1", message, latency, intent)
            return cached, {"source": "cache_L1", "latency_ms": latency}

        self.tracker.record_layer_miss("L1")

        # ── L2: Redis 精确匹配 ──
        t0 = time.time()
        cached = await self.L2.get(cache_key)
        if cached is not None:
            latency = (time.time() - t0) * 1000
            # 回填 L1
            self.L1.set(cache_key, cached)
            self.tracker.record_hit("L2", message, latency, intent)
            return cached, {"source": "cache_L2", "latency_ms": latency}

        self.tracker.record_layer_miss("L2")

        # ── L3: 语义相似度匹配 ──
        t0 = time.time()
        embedding = self._get_embedding(message)
        if embedding is not None:
            semantic_hit = self.L3.search(embedding)
            if semantic_hit is not None:
                latency = (time.time() - t0) * 1000
                # 回填 L1 + L2
                self.L1.set(cache_key, semantic_hit.answer)
                await self.L2.set(cache_key, semantic_hit.answer)
                self.tracker.record_hit("L3", message, latency, intent)
                return semantic_hit.answer, {
                    "source": "cache_L3_semantic",
                    "latency_ms": latency,
                    "similar_to": semantic_hit.question[:80],
                    "similarity_score": None,  # 无法从 search 返回中获取
                }

        self.tracker.record_layer_miss("L3")

        # ── 未命中 → 调用 LLM ──
        self.tracker.record_miss(message, intent)

        if compute_func is None:
            return "", {"source": "no_compute_func"}

        reply = await compute_func(message, intent)

        # ── 存入所有缓存层 ──
        if reply:
            self.L1.set(cache_key, reply, ttl=ttl)
            await self.L2.set(cache_key, reply, ttl=ttl or 300)

            # L3 语义缓存
            if embedding is not None:
                self.L3.store(
                    question=message,
                    answer=reply,
                    embedding=embedding,
                    intent=intent,
                    ttl=ttl,
                )

        return reply, {"source": "llm"}

    # ── 便捷方法 ──────────────────────────────────

    async def get_exact(self, message: str, intent: str = "", persona: str = "default") -> Optional[str]:
        """精确匹配查询 (不调 LLM)"""
        key = self._make_key(message, intent, persona)
        cached = self.L1.get(key)
        if cached:
            return cached
        cached = await self.L2.get(key)
        if cached:
            self.L1.set(key, cached)
            return cached
        return None

    async def set_exact(self, message: str, reply: str, intent: str = "", persona: str = "default", ttl: int = None):
        """手动设置精确缓存"""
        key = self._make_key(message, intent, persona)
        self.L1.set(key, reply, ttl=ttl)
        await self.L2.set(key, reply, ttl=ttl or 300)

    async def invalidate(self, message: str = None, intent: str = None, knowledge_id: str = None):
        """
        缓存失效

        触发场景:
        - 知识库更新 → invalidate knowledge_id
        - 人设更新 → invalidate 所有
        - 特定消息回复有误 → invalidate message
        """
        if knowledge_id:
            count = self.L3.invalidate_by_knowledge(knowledge_id)
            logger.info(f"Cache invalidated: {count} L3 entries for knowledge_id={knowledge_id}")

        if intent:
            count = self.L3.invalidate_by_intent(intent)
            self.L1.invalidate_by_tag(intent)
            await self.L2.delete_pattern(f"*:{intent}:*")
            logger.info(f"Cache invalidated: intent={intent}, L1 tags + L3 {count} entries")

        if message:
            key = self._make_key(message, "", "")
            self.L1.delete(key)
            await self.L2.delete(key)

    def clear_all(self):
        """清空所有缓存"""
        self.L1.clear()
        self.L3.clear()

    async def warm_up(self, faq_list: list):
        """
        缓存预热 — 在低峰期预计算常见问题的回复

        Args:
            faq_list: [{"question": "...", "answer": "..."}, ...]
        """
        count = 0
        for item in faq_list:
            q = item["question"]
            a = item["answer"]
            key = self._make_key(q, "", "default")
            embedding = self._get_embedding(q)

            self.L1.set(key, a, ttl=0)  # 永不过期
            await self.L2.set(key, a, ttl=0)

            if embedding is not None:
                self.L3.store(question=q, answer=a, embedding=embedding, ttl=0)

            count += 1

        logger.info(f"Cache warmed up with {count} FAQ entries")

    # ── 内部方法 ──────────────────────────────────

    def _make_key(self, message: str, intent: str = "", persona: str = "default") -> str:
        raw = f"{message.strip().lower()}|{intent}|{persona}"
        return "reply:" + hashlib.md5(raw.encode()).hexdigest()

    def _get_embedding(self, text: str):
        """获取文本 Embedding (懒加载模型)"""
        if self._embedding_model is None:
            try:
                from ..db.base import compute_embedding
                self._embedding_model = compute_embedding
            except Exception:
                return None
        try:
            emb = self._embedding_model(text)
            import numpy as np
            return np.array(emb)
        except Exception as e:
            logger.debug(f"Embedding failed: {e}")
            return None

    # ── 属性 ──────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool):
        self._enabled = value

    def get_summary(self) -> dict:
        return {
            "enabled": self._enabled,
            "L1": self.L1.get_stats(),
            "L3": self.L3.get_stats(),
            "tracker": self.tracker.get_summary(),
        }


# 全局单例
cache_manager = CacheManager()
