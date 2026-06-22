"""
L3 语义缓存 — 基于 Embedding 相似度的缓存匹配

不是精确 key 匹配，而是找到"意思相近"的已缓存问题和答案。
例如: "什么时候发货" ≈ "多久能发出" ≈ "发货要几天"
"""
import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field

import numpy as np
from loguru import logger


@dataclass
class SemanticEntry:
    question: str
    answer: str
    embedding: np.ndarray
    created_at: float
    ttl: float
    hit_count: int = 0
    last_hit: float = 0
    intent: str = ""
    knowledge_ids: list = field(default_factory=list)


class SemanticCache:
    """
    语义相似度缓存

    工作原理:
    1. 新问题到达 → 计算 embedding
    2. 与缓存中的所有问题做余弦相似度
    3. 相似度 > threshold → 返回缓存答案 (命中!)
    4. 相似度 < threshold → 调用 LLM → 结果存入缓存

    这样 "什么时候发货" 和 "多久能发出" 会命中同一条缓存
    """

    def __init__(self,
                 max_size: int = 5000,
                 similarity_threshold: float = 0.85,
                 default_ttl: float = 3600,
                 extended_ttl: float = 86400):
        """
        Args:
            max_size: 最大缓存条目数
            similarity_threshold: 余弦相似度阈值 (0-1), 越高越严格
            default_ttl: 默认 TTL (秒)
            extended_ttl: 高频命中条目的扩展 TTL (秒)
        """
        self._entries: List[SemanticEntry] = []
        self._max_size = max_size
        self._threshold = similarity_threshold
        self._default_ttl = default_ttl
        self._extended_ttl = extended_ttl

        # Embedding 矩阵 (n_entries × dim)
        self._embeddings: Optional[np.ndarray] = None

        # 统计
        self.hits = 0
        self.misses = 0
        self.false_positives = 0  # 命中但人工标记了不对

    def search(self, query_embedding: np.ndarray) -> Optional[SemanticEntry]:
        """
        搜索语义最匹配的缓存条目

        Args:
            query_embedding: 查询文本的 embedding 向量

        Returns:
            最匹配的 SemanticEntry (相似度 > threshold), 或 None
        """
        if self._embeddings is None or len(self._embeddings) == 0:
            self.misses += 1
            return None

        now = time.time()

        # 清理过期条目
        valid_indices = [
            i for i, e in enumerate(self._entries)
            if e.ttl == 0 or now - e.created_at < e.ttl
        ]

        if not valid_indices:
            self._entries = []
            self._embeddings = None
            self.misses += 1
            return None

        # 仅保留有效条目
        if len(valid_indices) < len(self._entries):
            self._entries = [self._entries[i] for i in valid_indices]
            self._embeddings = self._embeddings[valid_indices]

        # 计算余弦相似度
        query_vec = query_embedding.reshape(1, -1)
        similarities = np.dot(self._embeddings, query_vec.T).flatten()

        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        if best_score >= self._threshold:
            entry = self._entries[best_idx]
            entry.hit_count += 1
            entry.last_hit = now

            # 高频命中的条目延长 TTL
            if entry.hit_count >= 10 and entry.ttl < self._extended_ttl:
                entry.ttl = self._extended_ttl
                entry.created_at = now  # 刷新

            self.hits += 1
            logger.debug(f"Semantic cache HIT: score={best_score:.3f}, question='{entry.question[:50]}'")
            return entry

        self.misses += 1
        return None

    def store(self, question: str, answer: str, embedding: np.ndarray,
              intent: str = "", knowledge_ids: list = None, ttl: float = None):
        """
        存储新的语义缓存条目

        Args:
            question: 客户问题原文
            answer: AI 回复
            embedding: 问题的向量表示
            intent: 意图分类
            knowledge_ids: 使用的知识条目 ID
            ttl: TTL (秒), None 使用默认
        """
        ttl = ttl if ttl is not None else self._default_ttl

        entry = SemanticEntry(
            question=question,
            answer=answer,
            embedding=embedding,
            created_at=time.time(),
            ttl=ttl,
            intent=intent,
            knowledge_ids=knowledge_ids or [],
        )

        self._entries.append(entry)

        # 更新 embedding 矩阵
        if self._embeddings is None:
            self._embeddings = embedding.reshape(1, -1)
        else:
            self._embeddings = np.vstack([self._embeddings, embedding.reshape(1, -1)])

        # 超出容量 → 淘汰命中次数最少的
        if len(self._entries) > self._max_size:
            # 保留 hit_count 最高的条目
            keep_indices = sorted(
                range(len(self._entries)),
                key=lambda i: (self._entries[i].hit_count, self._entries[i].created_at),
                reverse=True,
            )[:self._max_size]

            self._entries = [self._entries[i] for i in keep_indices]
            self._embeddings = self._embeddings[keep_indices]

    def invalidate_by_knowledge(self, knowledge_id: str) -> int:
        """当知识库条目更新时, 失效相关缓存"""
        indices_to_keep = []
        removed = 0
        for i, e in enumerate(self._entries):
            if knowledge_id in e.knowledge_ids:
                removed += 1
            else:
                indices_to_keep.append(i)

        if removed > 0:
            self._entries = [self._entries[i] for i in indices_to_keep]
            self._embeddings = self._embeddings[indices_to_keep] if self._embeddings is not None else None

        logger.info(f"Semantic cache: invalidated {removed} entries for knowledge_id={knowledge_id}")
        return removed

    def invalidate_by_intent(self, intent: str) -> int:
        """按意图分类失效缓存"""
        indices_to_keep = []
        removed = 0
        for i, e in enumerate(self._entries):
            if e.intent == intent:
                removed += 1
            else:
                indices_to_keep.append(i)

        if removed > 0:
            self._entries = [self._entries[i] for i in indices_to_keep]
            self._embeddings = self._embeddings[indices_to_keep] if self._embeddings is not None else None

        return removed

    def clear(self):
        self._entries = []
        self._embeddings = None

    def mark_false_positive(self, question: str):
        """标记某条命中为误判, 降低后续匹配"""
        for e in self._entries:
            if e.question == question:
                e.hit_count = max(0, e.hit_count - 3)
                self.false_positives += 1
                break

    @property
    def size(self) -> int:
        return len(self._entries)

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0

    def get_stats(self) -> dict:
        return {
            "size": self.size,
            "max_size": self._max_size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate, 4),
            "false_positives": self.false_positives,
            "threshold": self._threshold,
            "top_entries": sorted(
                [{"question": e.question[:60], "hits": e.hit_count} for e in self._entries],
                key=lambda x: x["hits"], reverse=True,
            )[:10],
        }
