"""
向量数据库操作层
基于 pgvector 的向量检索、插入、索引管理
"""
import uuid
from typing import List, Dict, Optional, Tuple, Any
from datetime import datetime

from sqlalchemy import select, text, func, delete
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ..db.models import KnowledgeEmbedding, ConversationEmbedding
from ..db.base import compute_embedding, compute_embeddings


class VectorStore:
    """
    pgvector 向量操作封装

    支持:
    - 语义相似度检索
    - 批量向量插入
    - 索引维护
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── 检索 ──────────────────────────────────────

    async def search(self,
                     query: str,
                     top_k: int = 5,
                     content_type: str = None,
                     min_score: float = 0.5) -> List[Dict[str, Any]]:
        """
        语义检索

        Args:
            query: 查询文本
            top_k: 返回条数
            content_type: 过滤类型 (qa | product | policy)
            min_score: 最低余弦相似度
        """
        query_embedding = compute_embedding(query)

        # 构建 SQL
        conditions = [
            KnowledgeEmbedding.embedding.cosine_distance(query_embedding) < (1 - min_score)
        ]
        if content_type:
            conditions.append(KnowledgeEmbedding.content_type == content_type)

        # 执行查询
        distance = KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.knowledge_id,
                KnowledgeEmbedding.content,
                KnowledgeEmbedding.content_type,
                KnowledgeEmbedding.extra_meta,
                distance,
            )
            .where(*conditions)
            .order_by(distance)
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.fetchall()

        hits = []
        for row in rows:
            hits.append({
                "id": row.id,
                "knowledge_id": row.knowledge_id,
                "content": row.content,
                "content_type": row.content_type,
                "metadata": row.extra_meta or {},
                "score": round(1 - row.distance, 4),  # 转换为相似度
            })

        return hits

    async def search_by_product(self,
                                query: str,
                                product_id: str,
                                top_k: int = 3) -> List[Dict[str, Any]]:
        """带商品过滤的检索"""
        query_embedding = compute_embedding(query)

        distance = KnowledgeEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(
                KnowledgeEmbedding.id,
                KnowledgeEmbedding.content,
                KnowledgeEmbedding.extra_meta,
                distance,
            )
            .where(
                KnowledgeEmbedding.embedding.cosine_distance(query_embedding) < 0.5,
                KnowledgeEmbedding.extra_meta["product_id"].astext == product_id,
            )
            .order_by(distance)
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.fetchall()

        return [
            {
                "id": row.id,
                "content": row.content,
                "score": round(1 - row.distance, 4),
            }
            for row in rows
        ]

    async def search_similar_conversations(self,
                                           query: str,
                                           top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索相似历史对话"""
        query_embedding = compute_embedding(query)

        distance = ConversationEmbedding.embedding.cosine_distance(query_embedding).label("distance")

        stmt = (
            select(
                ConversationEmbedding.conversation_id,
                ConversationEmbedding.content,
                distance,
            )
            .where(
                ConversationEmbedding.embedding.cosine_distance(query_embedding) < 0.4
            )
            .order_by(distance)
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.fetchall()

        return [
            {
                "conversation_id": row.conversation_id,
                "content": row.content,
                "score": round(1 - row.distance, 4),
            }
            for row in rows
        ]

    # ── 插入 ──────────────────────────────────────

    async def insert_knowledge(self,
                               knowledge_id: str,
                               content: str,
                               content_type: str = "qa",
                               metadata: Optional[Dict] = None) -> str:
        """插入知识库向量"""
        embedding = compute_embedding(content)
        vid = str(uuid.uuid4())

        record = KnowledgeEmbedding(
            id=vid,
            knowledge_id=knowledge_id,
            content=content,
            content_type=content_type,
            embedding=embedding,
            extra_meta=metadata or {},
        )
        self.db.add(record)
        await self.db.flush()
        return vid

    async def insert_knowledge_batch(self,
                                     items: List[Dict[str, Any]]) -> List[str]:
        """批量插入知识库向量"""
        if not items:
            return []

        contents = [item["content"] for item in items]
        embeddings = compute_embeddings(contents)

        ids = []
        for item, embedding in zip(items, embeddings):
            vid = str(uuid.uuid4())
            record = KnowledgeEmbedding(
                id=vid,
                knowledge_id=item.get("knowledge_id"),
                content=item["content"],
                content_type=item.get("content_type", "qa"),
                embedding=embedding,
                extra_meta=item.get("metadata", {}),
            )
            self.db.add(record)
            ids.append(vid)

        await self.db.flush()
        return ids

    async def insert_conversation(self,
                                  conversation_id: str,
                                  content: str,
                                  metadata: Optional[Dict] = None) -> str:
        """插入对话向量"""
        embedding = compute_embedding(content)
        vid = str(uuid.uuid4())

        record = ConversationEmbedding(
            id=vid,
            conversation_id=conversation_id,
            content=content,
            embedding=embedding,
            extra_meta=metadata or {},
        )
        self.db.add(record)
        await self.db.flush()
        return vid

    # ── 更新/删除 ──────────────────────────────────

    async def update_embedding(self,
                               embedding_id: str,
                               content: str = None,
                               metadata: Optional[Dict] = None):
        """更新向量"""
        result = await self.db.execute(
            select(KnowledgeEmbedding).where(KnowledgeEmbedding.id == embedding_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            return

        if content:
            record.content = content
            record.embedding = compute_embedding(content)
        if metadata:
            record.extra_meta = metadata

        await self.db.flush()

    async def delete_knowledge(self, knowledge_id: str):
        """删除知识库向量"""
        await self.db.execute(
            delete(KnowledgeEmbedding).where(
                KnowledgeEmbedding.knowledge_id == knowledge_id
            )
        )
        await self.db.flush()

    async def delete_by_id(self, embedding_id: str):
        """按 ID 删除"""
        await self.db.execute(
            delete(KnowledgeEmbedding).where(
                KnowledgeEmbedding.id == embedding_id
            )
        )
        await self.db.flush()

    # ── 索引维护 ──────────────────────────────────

    async def build_index(self):
        """构建 IVFFlat 索引"""
        # 获取当前数据量
        result = await self.db.execute(
            select(func.count()).select_from(KnowledgeEmbedding)
        )
        count = result.scalar()

        if count < 1000:
            logger.info(f"Vector index: skipping (only {count} vectors, need 1000+)")
            return

        logger.info(f"Building IVFFlat index on {count} vectors...")

        await self.db.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_embedding_vector
            ON knowledge_embeddings
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = :lists)
        """), {"lists": min(200, max(10, count // 1000))})

        await self.db.commit()

    async def get_stats(self) -> Dict[str, Any]:
        """向量库统计"""
        result = await self.db.execute(
            select(
                KnowledgeEmbedding.content_type,
                func.count().label("cnt"),
            ).group_by(KnowledgeEmbedding.content_type)
        )
        type_stats = {row.content_type: row.cnt for row in result.fetchall()}

        total_result = await self.db.execute(
            select(func.count()).select_from(KnowledgeEmbedding)
        )
        total = total_result.scalar()

        conv_result = await self.db.execute(
            select(func.count()).select_from(ConversationEmbedding)
        )
        conv_total = conv_result.scalar()

        return {
            "total_vectors": total,
            "total_conversation_vectors": conv_total,
            "by_type": type_stats,
        }
