"""
KnowledgeBaseTool -- Primary agent tool for knowledge base CRUD, semantic search,
and auto-learn workflow.

Role:
1. Look up answers via vector search BEFORE the agent responds
2. Record new information learned from conversations
3. Flag missing knowledge (gaps) for human review

Uses dependency injection: receives a ``db_factory`` callable in the constructor
(e.g. ``sqlalchemy.ext.asyncio.async_sessionmaker``) and opens sessions only when
a method is called.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import func, select, update as sa_update

from ..db.models import (
    KnowledgeItem,
    KnowledgeEmbedding,
    KnowledgeGap,
    KnowledgeReview,
)
from ..db.vector import VectorStore
from ..db.base import compute_embedding
from .base import BaseTool, ToolResult


class KnowledgeBaseTool(BaseTool):
    """
    Knowledge base CRUD + semantic search tool.

    Compatible with ToolRegistry (via ``execute()``) and also usable standalone
    via its public async methods.
    """

    name = "knowledge_base"
    description = (
        "Search and manage the customer-service knowledge base. "
        "Use for: finding FAQ answers, adding new knowledge, "
        "updating outdated information, recording knowledge gaps."
    )
    category = "knowledge"

    parameters = {
        "action": {
            "type": "string",
            "enum": ["search", "add", "update", "suggest_gap", "delete"],
            "description": (
                "search: semantic search by query | "
                "add: create a new knowledge entry (needs question+answer) | "
                "update: modify an existing entry by id | "
                "suggest_gap: flag a question the system could not answer | "
                "delete: remove an entry by id"
            ),
        },
        "query": {
            "type": "string",
            "description": "Search keywords or gap question (action=search/suggest_gap).",
        },
        "question": {
            "type": "string",
            "description": "Question text (action=add/update).",
        },
        "answer": {
            "type": "string",
            "description": "Answer text (action=add/update).",
        },
        "category": {
            "type": "string",
            "description": "Category label (action=add).",
        },
        "knowledge_id": {
            "type": "string",
            "description": "Knowledge entry ID (action=update/delete).",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return.",
            "default": 5,
        },
    }

    # ------------------------------------------------------------------
    #  Constructor
    # ------------------------------------------------------------------

    def __init__(self, db_factory=None):
        """
        Args:
            db_factory: An async callable returning an async context manager
                        that yields an AsyncSession.  Typically the
                        ``async_sessionmaker`` from ``server.db.base``.
        """
        self.db_factory = db_factory

    # ------------------------------------------------------------------
    #  execute -- ToolRegistry dispatch
    # ------------------------------------------------------------------

    async def execute(self, action: str, **kwargs) -> ToolResult:
        """Entry-point used by ToolRegistry."""
        try:
            if action == "search":
                hits = await self.search(
                    query=kwargs.get("query", ""),
                    top_k=int(kwargs.get("top_k", 5)),
                )
                return ToolResult(success=True, data=hits)

            elif action == "add":
                result = await self.add(
                    question=kwargs.get("question", ""),
                    answer=kwargs.get("answer", ""),
                    category=kwargs.get("category"),
                )
                return ToolResult(success=True, data=result)

            elif action == "update":
                result = await self.update(
                    knowledge_id=kwargs.get("knowledge_id", ""),
                    question=kwargs.get("question"),
                    answer=kwargs.get("answer"),
                )
                if result is None:
                    return ToolResult(
                        success=False,
                        error=f"Knowledge item {kwargs.get('knowledge_id')} not found",
                    )
                return ToolResult(success=True, data=result)

            elif action == "suggest_gap":
                gap = await self.suggest_gap(query=kwargs.get("query", ""))
                return ToolResult(success=True, data=gap)

            elif action == "delete":
                deleted = await self.delete(knowledge_id=kwargs.get("knowledge_id", ""))
                return ToolResult(success=True, data={"deleted": deleted})

            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")

        except Exception as exc:
            logger.exception(f"KnowledgeBaseTool.{action} failed")
            return ToolResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    #  Public API -- search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search over the knowledge base.

        Returns enriched hits that join vector results with KnowledgeItem
        metadata (question, answer, category, source, status, etc.).
        """
        if not self.db_factory:
            logger.warning("KnowledgeBaseTool.search: db_factory is None")
            return []

        async with self.db_factory() as db:
            vs = VectorStore(db)
            raw_hits = await vs.search(query, top_k=top_k, min_score=min_score)

            if not raw_hits:
                return []

            # Batch-fetch KnowledgeItem rows for full metadata
            kid_to_hit: Dict[str, Dict[str, Any]] = {}
            kids: List[str] = []
            for h in raw_hits:
                kid = h.get("knowledge_id")
                if kid:
                    kid_to_hit[kid] = h
                    kids.append(kid)

            if not kids:
                # No knowledge_id links -- return raw hits as-is
                return [
                    {
                        "id": h["id"],
                        "knowledge_id": h.get("knowledge_id"),
                        "question": "",
                        "answer": "",
                        "category": None,
                        "source": "",
                        "status": "unknown",
                        "confidence": 0.0,
                        "usage_count": 0,
                        "score": h["score"],
                        "content": h["content"],
                        "content_type": h["content_type"],
                        "metadata": h.get("metadata", {}),
                    }
                    for h in raw_hits
                ]

            stmt = select(KnowledgeItem).where(KnowledgeItem.id.in_(kids))
            result = await db.execute(stmt)
            item_rows = {r.id: r for r in result.scalars().all()}

            enriched: List[Dict[str, Any]] = []
            for kid, hit in kid_to_hit.items():
                item = item_rows.get(kid)
                enriched.append({
                    "id": hit["id"],
                    "knowledge_id": kid,
                    "question": item.question if item else "",
                    "answer": item.answer if item else "",
                    "category": item.category if item else None,
                    "source": item.source if item else "",
                    "status": item.status if item else "unknown",
                    "confidence": item.confidence if item else 0.0,
                    "usage_count": item.usage_count if item else 0,
                    "score": hit["score"],
                    "content": hit["content"],
                    "content_type": hit["content_type"],
                    "metadata": hit.get("metadata", {}),
                })

            return enriched

    # ------------------------------------------------------------------
    #  Public API -- add
    # ------------------------------------------------------------------

    async def add(
        self,
        question: str,
        answer: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        source: str = "manual",
        confidence: float = 1.0,
        status: str = "active",
    ) -> Dict[str, Any]:
        """
        Add a new knowledge-base entry with its vector embedding.

        Args:
            question: Customer question.
            answer: Desired answer.
            category: Optional category.
            tags: Optional tag list.
            source: Origin -- ``manual``, ``auto_learned``, ``seed``, etc.
            confidence: Confidence 0.0-1.0 (auto-learned items).
            status: ``active``, ``pending_review``, or ``archived``.

        Returns:
            Dict with ``id``, ``embedding_id``, ``question``, ``answer``, etc.
        """
        if not question or not answer:
            raise ValueError("question and answer are required")

        if not self.db_factory:
            raise RuntimeError("Database not available (db_factory is None)")

        async with self.db_factory() as db:
            vs = VectorStore(db)

            kid = uuid.uuid4().hex

            # 1. KnowledgeItem row
            item = KnowledgeItem(
                id=kid,
                question=question,
                answer=answer,
                category=category,
                tags=tags or [],
                source=source,
                confidence=confidence,
                status=status,
                usage_count=0,
                success_count=0,
            )
            db.add(item)

            # 2. Vector embedding
            embed_content = f"{question}\n{answer}"
            embedding_id = await vs.insert_knowledge(
                knowledge_id=kid,
                content=embed_content,
                content_type="qa",
                metadata={"category": category, "source": source},
            )

            # 3. Link
            item.embedding_id = embedding_id

            await db.commit()

            logger.info(
                f"KnowledgeBase: added id={kid} "
                f"category={category} source={source}"
            )

            return {
                "id": kid,
                "embedding_id": embedding_id,
                "question": question,
                "answer": answer,
                "category": category,
                "source": source,
                "status": status,
            }

    # ------------------------------------------------------------------
    #  Public API -- update
    # ------------------------------------------------------------------

    async def update(
        self,
        knowledge_id: str,
        question: Optional[str] = None,
        answer: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing knowledge entry.  Re-computes the vector embedding
        when question or answer changes.

        Returns the updated entry dict, or None if not found.
        """
        if not self.db_factory:
            raise RuntimeError("Database not available (db_factory is None)")

        async with self.db_factory() as db:
            result = await db.execute(
                select(KnowledgeItem).where(KnowledgeItem.id == knowledge_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                logger.warning(f"KnowledgeBase: update failed -- id={knowledge_id} not found")
                return None

            content_changed = False

            if question is not None and question != item.question:
                item.question = question
                content_changed = True
            if answer is not None and answer != item.answer:
                item.answer = answer
                content_changed = True
            if category is not None:
                item.category = category
            if tags is not None:
                item.tags = tags
            if status is not None:
                item.status = status

            await db.flush()

            # Re-compute embedding when content changed
            if content_changed and item.embedding_id:
                vs = VectorStore(db)
                new_content = f"{item.question}\n{item.answer}"
                await vs.update_embedding(
                    embedding_id=item.embedding_id,
                    content=new_content,
                    metadata={"category": item.category, "source": item.source},
                )

            await db.commit()

            logger.info(f"KnowledgeBase: updated id={knowledge_id}")

            return {
                "id": item.id,
                "embedding_id": item.embedding_id,
                "question": item.question,
                "answer": item.answer,
                "category": item.category,
                "tags": item.tags,
                "source": item.source,
                "confidence": item.confidence,
                "status": item.status,
            }

    # ------------------------------------------------------------------
    #  Public API -- delete
    # ------------------------------------------------------------------

    async def delete(self, knowledge_id: str) -> bool:
        """Hard-delete a knowledge entry and its embedding vector."""
        if not self.db_factory:
            return False

        async with self.db_factory() as db:
            vs = VectorStore(db)

            result = await db.execute(
                select(KnowledgeItem).where(KnowledgeItem.id == knowledge_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False

            if item.embedding_id:
                await vs.delete_knowledge(knowledge_id)

            await db.delete(item)
            await db.commit()

            logger.info(f"KnowledgeBase: deleted id={knowledge_id}")
            return True

    async def archive(self, knowledge_id: str) -> bool:
        """Soft-delete: set status to ``archived``."""
        return await self.update(knowledge_id, status="archived") is not None

    # ------------------------------------------------------------------
    #  Public API -- suggest_gap
    # ------------------------------------------------------------------

    async def suggest_gap(
        self,
        query: str,
        normalized_question: Optional[str] = None,
        suggested_category: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Record a knowledge gap -- a question the system could not answer.

        If the same raw query is already recorded (open), its frequency is
        incremented rather than creating a duplicate.

        Returns dict with ``id``, ``frequency``, ``action`` (created / incremented).
        """
        if not query:
            raise ValueError("query is required")

        if not self.db_factory:
            return {
                "id": "",
                "frequency": 1,
                "action": "not_persisted",
                "raw_question": query,
                "status": "open",
            }

        async with self.db_factory() as db:
            stmt = (
                select(KnowledgeGap)
                .where(
                    KnowledgeGap.raw_question == query,
                    KnowledgeGap.status == "open",
                )
                .limit(1)
            )
            result = await db.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.frequency += 1
                if normalized_question:
                    existing.normalized_question = normalized_question
                if suggested_category:
                    existing.suggested_category = suggested_category
                await db.commit()
                logger.info(
                    f"KnowledgeBase: incremented gap id={existing.id} freq={existing.frequency}"
                )
                return {
                    "id": existing.id,
                    "frequency": existing.frequency,
                    "action": "incremented",
                    "raw_question": existing.raw_question,
                    "status": existing.status,
                }

            # New gap
            gap_id = uuid.uuid4().hex
            gap = KnowledgeGap(
                id=gap_id,
                raw_question=query,
                normalized_question=normalized_question or query,
                frequency=1,
                suggested_category=suggested_category,
                status="open",
            )
            db.add(gap)
            await db.commit()

            logger.info(
                f"KnowledgeBase: created gap id={gap_id} query='{query[:80]}'"
            )
            return {
                "id": gap_id,
                "frequency": 1,
                "action": "created",
                "raw_question": query,
                "status": "open",
            }

    # ------------------------------------------------------------------
    #  Public API -- get_stats
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """
        Return comprehensive knowledge-base statistics.

        Returns dict with:
            total_items, active_items, pending_review, archived,
            by_category, by_source, avg_confidence, total_usage,
            review_queue_count, open_gaps, vector_stats
        """
        if not self.db_factory:
            return {"error": "Database not available"}

        async with self.db_factory() as db:
            vs = VectorStore(db)

            # --- KnowledgeItem stats ---
            total_stmt = select(func.count()).select_from(KnowledgeItem)
            total_items = (await db.execute(total_stmt)).scalar() or 0

            active_stmt = (
                select(func.count())
                .select_from(KnowledgeItem)
                .where(KnowledgeItem.status == "active")
            )
            active_items = (await db.execute(active_stmt)).scalar() or 0

            pending_stmt = (
                select(func.count())
                .select_from(KnowledgeItem)
                .where(KnowledgeItem.status == "pending_review")
            )
            pending_review = (await db.execute(pending_stmt)).scalar() or 0

            archived_stmt = (
                select(func.count())
                .select_from(KnowledgeItem)
                .where(KnowledgeItem.status == "archived")
            )
            archived = (await db.execute(archived_stmt)).scalar() or 0

            # By category
            cat_stmt = (
                select(KnowledgeItem.category, func.count().label("cnt"))
                .where(KnowledgeItem.status == "active")
                .group_by(KnowledgeItem.category)
                .order_by(func.count().desc())
            )
            cat_res = await db.execute(cat_stmt)
            by_category = {
                (row.category or "uncategorized"): row.cnt
                for row in cat_res.fetchall()
            }

            # By source
            src_stmt = (
                select(KnowledgeItem.source, func.count().label("cnt"))
                .group_by(KnowledgeItem.source)
                .order_by(func.count().desc())
            )
            src_res = await db.execute(src_stmt)
            by_source = {
                (r.source or "unknown"): r.cnt for r in src_res.fetchall()
            }

            # Aggregates
            agg_stmt = select(
                func.avg(KnowledgeItem.confidence).label("avg_conf"),
                func.sum(KnowledgeItem.usage_count).label("total_usage"),
            )
            agg_res = await db.execute(agg_stmt)
            agg_row = agg_res.one()
            avg_confidence = round(float(agg_row.avg_conf or 0), 3)
            total_usage = int(agg_row.total_usage or 0)

            # Review queue
            review_stmt = (
                select(func.count())
                .select_from(KnowledgeReview)
                .where(KnowledgeReview.status == "pending")
            )
            review_count = (await db.execute(review_stmt)).scalar() or 0

            # Open gaps
            gap_stmt = (
                select(func.count())
                .select_from(KnowledgeGap)
                .where(KnowledgeGap.status == "open")
            )
            open_gaps = (await db.execute(gap_stmt)).scalar() or 0

            # Vector store stats
            vector_stats = await vs.get_stats()

            return {
                "total_items": total_items,
                "active_items": active_items,
                "pending_review": pending_review,
                "archived": archived,
                "by_category": by_category,
                "by_source": by_source,
                "avg_confidence": avg_confidence,
                "total_usage": total_usage,
                "review_queue_count": review_count,
                "open_gaps": open_gaps,
                "vector_stats": vector_stats,
            }

    # ------------------------------------------------------------------
    #  Utility -- record_hit / record_success
    # ------------------------------------------------------------------

    async def record_hit(self, knowledge_id: str) -> None:
        """Increment usage_count for a knowledge item (call after a successful lookup)."""
        if not self.db_factory:
            return
        async with self.db_factory() as db:
            await db.execute(
                sa_update(KnowledgeItem)
                .where(KnowledgeItem.id == knowledge_id)
                .values(usage_count=KnowledgeItem.usage_count + 1)
            )
            await db.commit()

    async def record_success(self, knowledge_id: str) -> None:
        """Increment success_count (call when the answer resolved the conversation)."""
        if not self.db_factory:
            return
        async with self.db_factory() as db:
            await db.execute(
                sa_update(KnowledgeItem)
                .where(KnowledgeItem.id == knowledge_id)
                .values(success_count=KnowledgeItem.success_count + 1)
            )
            await db.commit()

    # ------------------------------------------------------------------
    #  Utility -- list / browse
    # ------------------------------------------------------------------

    async def list_items(
        self,
        category: Optional[str] = None,
        status: str = "active",
        source: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Paginated listing of knowledge items."""
        if not self.db_factory:
            return []

        async with self.db_factory() as db:
            stmt = select(KnowledgeItem)

            if category:
                stmt = stmt.where(KnowledgeItem.category == category)
            if status:
                stmt = stmt.where(KnowledgeItem.status == status)
            if source:
                stmt = stmt.where(KnowledgeItem.source == source)

            stmt = stmt.order_by(KnowledgeItem.updated_at.desc()).offset(offset).limit(limit)

            res = await db.execute(stmt)
            rows = res.scalars().all()

            return [
                {
                    "id": r.id,
                    "question": r.question,
                    "answer": r.answer,
                    "category": r.category,
                    "source": r.source,
                    "confidence": r.confidence,
                    "usage_count": r.usage_count,
                    "success_count": r.success_count,
                    "status": r.status,
                    "tags": r.tags,
                    "created_at": str(r.created_at) if r.created_at else None,
                    "updated_at": str(r.updated_at) if r.updated_at else None,
                }
                for r in rows
            ]

    async def get_by_id(self, knowledge_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single knowledge item by id."""
        if not self.db_factory:
            return None

        async with self.db_factory() as db:
            res = await db.execute(
                select(KnowledgeItem).where(KnowledgeItem.id == knowledge_id)
            )
            item = res.scalar_one_or_none()
            if item is None:
                return None

            return {
                "id": item.id,
                "embedding_id": item.embedding_id,
                "question": item.question,
                "answer": item.answer,
                "category": item.category,
                "tags": item.tags,
                "source": item.source,
                "source_conversation_id": item.source_conversation_id,
                "confidence": item.confidence,
                "usage_count": item.usage_count,
                "success_count": item.success_count,
                "status": item.status,
                "created_at": str(item.created_at) if item.created_at else None,
                "updated_at": str(item.updated_at) if item.updated_at else None,
            }

    async def list_gaps(
        self,
        status: str = "open",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List knowledge gaps ordered by frequency descending."""
        if not self.db_factory:
            return []

        async with self.db_factory() as db:
            stmt = (
                select(KnowledgeGap)
                .where(KnowledgeGap.status == status)
                .order_by(KnowledgeGap.frequency.desc())
                .limit(limit)
            )
            res = await db.execute(stmt)
            rows = res.scalars().all()

            return [
                {
                    "id": r.id,
                    "raw_question": r.raw_question,
                    "normalized_question": r.normalized_question,
                    "frequency": r.frequency,
                    "suggested_category": r.suggested_category,
                    "status": r.status,
                    "created_at": str(r.created_at) if r.created_at else None,
                }
                for r in rows
            ]

    async def resolve_gap(self, gap_id: str) -> bool:
        """Mark a knowledge gap as resolved."""
        if not self.db_factory:
            return False

        async with self.db_factory() as db:
            res = await db.execute(
                select(KnowledgeGap).where(KnowledgeGap.id == gap_id)
            )
            gap = res.scalar_one_or_none()
            if gap is None:
                return False
            gap.status = "resolved"
            await db.commit()
            return True
