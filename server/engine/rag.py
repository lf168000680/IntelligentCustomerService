"""
RAG 检索器 — 从知识库检索相关内容
支持多路召回 + 重排序
"""
from typing import List, Dict, Optional, Any, Tuple
from loguru import logger

# 惰性导入，允许在没有 pgvector 环境时运行基础功能
VectorStore = None
try:
    from ..db.vector import VectorStore as _VectorStore
    VectorStore = _VectorStore
except ImportError:
    pass


class RAGRetriever:
    """
    RAG (Retrieval-Augmented Generation) 检索器

    检索策略:
    1. 向量语义检索 (pgvector)
    2. 关键词精确匹配 (PostgreSQL FTS)
    3. 重排序 (cross-encoder 或 LLM)
    """

    def __init__(self, db_session, llm_router=None):
        self.vector_store = VectorStore(db_session)
        self.db = db_session
        self.router = llm_router

    async def retrieve(self,
                       query: str,
                       top_k: int = 5,
                       filters: Dict[str, Any] = None,
                       min_score: float = 0.5,
                       use_rerank: bool = True) -> List[Dict[str, Any]]:
        """
        多路召回

        Args:
            query: 客户问题
            top_k: 返回条数
            filters: 过滤条件 {product_id, category, content_type}
            min_score: 最低相似度

        Returns:
            [
                {
                    "id": "...",
                    "knowledge_id": "...",
                    "question": "原问题",
                    "answer": "答案",
                    "content": "检索到的内容",
                    "score": 0.92,
                    "source": "vector" | "keyword" | "product",
                    "metadata": {...}
                }
            ]
        """
        all_hits = []

        # ── 召回 1: 向量语义检索 ──
        try:
            vector_hits = await self.vector_store.search(
                query=query,
                top_k=top_k * 2,  # 多召回一些用于重排
                min_score=min_score,
            )
            for h in vector_hits:
                all_hits.append({**h, "source": "vector"})
        except Exception as e:
            logger.error(f"Vector search error: {e}")

        # ── 召回 2: 关键词精确匹配 ──
        try:
            keyword_hits = await self._keyword_search(query, top_k)
            for h in keyword_hits:
                # 去重
                if not any(a.get("knowledge_id") == h.get("knowledge_id") for a in all_hits):
                    all_hits.append({**h, "source": "keyword"})
        except Exception as e:
            logger.warning(f"Keyword search error: {e}")

        # ── 召回 3: 相关商品信息 ──
        if filters and filters.get("product_id"):
            try:
                product_hits = await self.vector_store.search_by_product(
                    query=query,
                    product_id=filters["product_id"],
                    top_k=2,
                )
                for h in product_hits:
                    if not any(a.get("knowledge_id") == h.get("knowledge_id") for a in all_hits):
                        all_hits.append({**h, "source": "product"})
            except Exception as e:
                logger.warning(f"Product search error: {e}")

        # 按分数排序
        all_hits.sort(key=lambda x: x.get("score", 0), reverse=True)

        # ── 去重 + 截断 ──
        seen_content = set()
        unique_hits = []
        for hit in all_hits:
            content_hash = hash(hit.get("content", "")[:100])
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_hits.append(hit)

        # ── 重排序 (可选) ──
        if use_rerank and len(unique_hits) > top_k and self.router:
            try:
                unique_hits = await self._llm_rerank(query, unique_hits, top_k)
            except Exception as e:
                logger.warning(f"Rerank error: {e}")
                unique_hits = unique_hits[:top_k]
        else:
            unique_hits = unique_hits[:top_k]

        # 补充完整 Q&A 信息
        enriched = await self._enrich_hits(unique_hits)

        return enriched

    async def retrieve_simple(self, query: str, top_k: int = 3) -> List[str]:
        """简单检索 → 直接返回文本列表（用于构建 prompt）"""
        hits = await self.retrieve(query, top_k=top_k, use_rerank=False)
        return [h.get("answer", h.get("content", "")) for h in hits]

    # ── 内部方法 ──────────────────────────────────

    async def _keyword_search(self, query: str, top_k: int) -> List[Dict]:
        """PostgreSQL 全文搜索"""
        from sqlalchemy import select, func, text as sa_text
        from ..db.models import KnowledgeItem

        # 使用 pg_trgm 做模糊匹配
        stmt = (
            select(
                KnowledgeItem.id.label("knowledge_id"),
                KnowledgeItem.question,
                KnowledgeItem.answer.label("content"),
                func.similarity(KnowledgeItem.question, query).label("score"),
            )
            .where(
                func.similarity(KnowledgeItem.question, query) > 0.2,
                KnowledgeItem.status == "active",
            )
            .order_by(func.similarity(KnowledgeItem.question, query).desc())
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.fetchall()

        return [
            {
                "knowledge_id": row.knowledge_id,
                "content": f"{row.question}\n{row.content}",
                "score": round(row.score, 4),
                "question": row.question,
                "answer": row.content,
            }
            for row in rows
        ]

    async def _llm_rerank(self, query: str, hits: List[Dict], top_k: int) -> List[Dict]:
        """LLM 重排序 — 用 cheap 模型选出最相关的"""
        import json

        candidates_text = []
        for i, h in enumerate(hits):
            content = h.get("content", "")[:300]
            candidates_text.append(f"[{i}] {content}")

        prompt = f"""用户问题: "{query}"

从以下候选中选出最相关的 {top_k} 条。只输出 JSON 数组，不要解释。

候选:
{chr(10).join(candidates_text)}

输出格式: [0, 2, 5]  (按相关性降序排列)

JSON:"""

        msgs = [{"role": "user", "content": prompt}]
        from ..llm.base import LLMRequest
        try:
            result = await self.router.generate(
                LLMRequest(messages=msgs, max_tokens=50, temperature=0, preferred_tag="cheap"),
                scene="cheap",
            )
            indices = json.loads(result.strip().strip("`"))
            return [hits[i] for i in indices if 0 <= i < len(hits)]
        except:
            return hits[:top_k]

    async def _enrich_hits(self, hits: List[Dict]) -> List[Dict]:
        """补充完整 Q&A 信息"""
        knowledge_ids = [h.get("knowledge_id") for h in hits if h.get("knowledge_id")]
        if not knowledge_ids:
            return hits

        from sqlalchemy import select
        from ..db.models import KnowledgeItem

        result = await self.db.execute(
            select(KnowledgeItem).where(KnowledgeItem.id.in_(knowledge_ids))
        )
        records = {r.id: r for r in result.scalars().all()}

        enriched = []
        for hit in hits:
            kid = hit.get("knowledge_id")
            if kid and kid in records:
                r = records[kid]
                enriched.append({
                    **hit,
                    "question": r.question,
                    "answer": r.answer,
                    "category": r.category,
                    "confidence": r.confidence,
                })
            else:
                enriched.append(hit)

        return enriched
