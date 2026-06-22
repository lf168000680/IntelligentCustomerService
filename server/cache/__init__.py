"""
Kefu 多级缓存系统
L1: 内存 LRU + TTL (毫秒级)
L2: Redis 共享缓存 (分布式)
L3: 语义相似度缓存 (Embedding 匹配)
"""
from .manager import CacheManager, cache_manager
from .memory_cache import MemoryCache
from .redis_cache import RedisCache
from .semantic_cache import SemanticCache
from .hit_tracker import HitTracker

__all__ = [
    "CacheManager", "cache_manager",
    "MemoryCache", "RedisCache", "SemanticCache",
    "HitTracker",
]
