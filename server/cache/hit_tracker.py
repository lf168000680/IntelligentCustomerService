"""
缓存命中追踪 & 分析
"""
import time
from collections import defaultdict, deque
from typing import Dict, List, Any
from dataclasses import dataclass, field


@dataclass
class HitRecord:
    timestamp: float
    layer: str          # L1 | L2 | L3
    query: str
    result: str         # hit | miss
    latency_ms: float
    intent: str = ""


class HitTracker:
    """
    缓存命中追踪器

    记录每次缓存查询的:
    - 命中/未命中
    - 命中层级 (L1/L2/L3)
    - 延迟
    - 意图分布
    """

    def __init__(self, window_size: int = 10000, retention_seconds: int = 86400):
        self._records: deque = deque(maxlen=window_size)
        self._retention = retention_seconds

        # 按层级统计
        self._layer_hits = defaultdict(int)
        self._layer_misses = defaultdict(int)

        # 按意图统计
        self._intent_hits = defaultdict(int)
        self._intent_misses = defaultdict(int)

        # 时间窗口统计
        self._hourly_hits: Dict[int, int] = defaultdict(int)
        self._hourly_misses: Dict[int, int] = defaultdict(int)

        # 累计
        self.total_requests = 0
        self.total_hits = 0
        self.total_llm_calls = 0
        self.total_latency_saved_ms = 0  # 估算节省的延迟

    def record_hit(self, layer: str, query: str, latency_ms: float, intent: str = ""):
        """记录一次缓存命中"""
        record = HitRecord(
            timestamp=time.time(),
            layer=layer,
            query=query,
            result="hit",
            latency_ms=latency_ms,
            intent=intent,
        )
        self._records.append(record)
        self._layer_hits[layer] += 1
        self._intent_hits[intent] += 1
        self.total_requests += 1
        self.total_hits += 1

        # 估算节省的延迟 (命中只需 1-5ms vs LLM 1000-3000ms)
        self.total_latency_saved_ms += 1500

        hour = int(time.time() // 3600)
        self._hourly_hits[hour] += 1

    def record_miss(self, query: str, intent: str = ""):
        """记录一次缓存未命中"""
        record = HitRecord(
            timestamp=time.time(),
            layer="miss",
            query=query,
            result="miss",
            latency_ms=0,
            intent=intent,
        )
        self._records.append(record)
        self.total_requests += 1
        self.total_llm_calls += 1
        self._intent_misses[intent] += 1

        hour = int(time.time() // 3600)
        self._hourly_misses[hour] += 1

    def record_layer_miss(self, layer: str):
        """记录某一层未命中"""
        self._layer_misses[layer] += 1

    @property
    def overall_hit_rate(self) -> float:
        if self.total_requests == 0:
            return 0
        return self.total_hits / self.total_requests

    @property
    def llm_saved(self) -> float:
        """估算节省的 LLM 调用费用"""
        # 假设每次 LLM 调用 $0.01
        return self.total_hits * 0.01

    def get_summary(self) -> dict:
        """获取缓存摘要"""
        now = time.time()
        recent_hits = sum(
            1 for r in self._records
            if r.result == "hit" and now - r.timestamp < 3600
        )
        recent_total = sum(
            1 for r in self._records
            if now - r.timestamp < 3600
        )

        return {
            "total_requests": self.total_requests,
            "total_hits": self.total_hits,
            "total_llm_calls": self.total_llm_calls,
            "overall_hit_rate": round(self.overall_hit_rate, 4),
            "recent_hit_rate": round(recent_hits / recent_total, 4) if recent_total else 0,
            "latency_saved_seconds": round(self.total_latency_saved_ms / 1000, 1),
            "estimated_cost_saved": round(self.llm_saved, 2),
            "layer_stats": {
                "L1_memory": {
                    "hits": self._layer_hits.get("L1", 0),
                    "misses": self._layer_misses.get("L1", 0),
                },
                "L2_redis": {
                    "hits": self._layer_hits.get("L2", 0),
                    "misses": self._layer_misses.get("L2", 0),
                },
                "L3_semantic": {
                    "hits": self._layer_hits.get("L3", 0),
                    "misses": self._layer_misses.get("L3", 0),
                },
            },
            "top_intent_hits": dict(
                sorted(self._intent_hits.items(), key=lambda x: x[1], reverse=True)[:5]
            ),
        }

    def get_hourly_trend(self) -> dict:
        """获取每小时缓存趋势"""
        return {
            "hits": dict(self._hourly_hits),
            "misses": dict(self._hourly_misses),
        }

    def reset(self):
        self._records.clear()
        self._layer_hits.clear()
        self._layer_misses.clear()
        self._intent_hits.clear()
        self._intent_misses.clear()
        self.total_requests = 0
        self.total_hits = 0
        self.total_llm_calls = 0
        self.total_latency_saved_ms = 0
