"""
L1 内存缓存 — LRU 淘汰 + TTL 过期
"""
import time
import hashlib
import threading
from typing import Dict, Optional, Any, Tuple
from dataclasses import dataclass, field
from collections import OrderedDict
from loguru import logger


@dataclass
class CacheEntry:
    key: str
    value: Any
    created_at: float
    ttl: float                         # 存活秒数, 0 = 永不过期
    access_count: int = 0
    last_access: float = 0
    tags: set = field(default_factory=set)


class MemoryCache:
    """
    线程安全的 LRU 内存缓存

    特性:
    - 最大容量限制, 超出时淘汰最久未使用条目
    - 每条条目独立 TTL
    - 按标签批量失效
    - 命中统计
    """

    def __init__(self, max_size: int = 10000, default_ttl: float = 300):
        self._store: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        self._max_size = max_size
        self._default_ttl = default_ttl

        # 统计
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.expirations = 0

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值, 命中返回数据, 未命中返回 None"""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None

            # 检查 TTL
            if entry.ttl > 0 and time.time() - entry.created_at > entry.ttl:
                del self._store[key]
                self.expirations += 1
                self.misses += 1
                return None

            # 移到末尾 (最近使用)
            self._store.move_to_end(key)
            entry.access_count += 1
            entry.last_access = time.time()
            self.hits += 1
            return entry.value

    def set(self, key: str, value: Any, ttl: float = None, tags: set = None):
        """设置缓存值"""
        with self._lock:
            ttl = ttl if ttl is not None else self._default_ttl
            entry = CacheEntry(
                key=key,
                value=value,
                created_at=time.time(),
                ttl=ttl,
                last_access=time.time(),
                tags=tags or set(),
            )

            if key in self._store:
                self._store.move_to_end(key)
            else:
                # 检查容量
                while len(self._store) >= self._max_size:
                    oldest_key, _ = self._store.popitem(last=False)
                    self.evictions += 1

            self._store[key] = entry

    def delete(self, key: str):
        with self._lock:
            self._store.pop(key, None)

    def invalidate_by_tag(self, tag: str) -> int:
        """按标签批量失效, 返回清除的条目数"""
        with self._lock:
            keys_to_delete = [
                k for k, v in self._store.items()
                if tag in v.tags
            ]
            for k in keys_to_delete:
                del self._store[k]
            return len(keys_to_delete)

    def clear(self):
        with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        return len(self._store)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0

    def make_key(self, *args, **kwargs) -> str:
        """生成缓存 key"""
        raw = "|".join(str(a) for a in args)
        if kwargs:
            raw += "|" + "|".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        return hashlib.md5(raw.encode()).hexdigest()

    def get_stats(self) -> dict:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "evictions": self.evictions,
            "expirations": self.expirations,
        }
