"""
知识库自主学习 Pipeline

每日自动运行:
1. 拉取过去24h对话 → 2. 清洗 → 3. 提取客户问题
4. Embedding 聚类 → 5. 生成标准 Q&A → 6. 入库/审核队列
7. 发现知识缺口 → 8. 更新 MEMORY → 9. 生成日报
"""
import re
import json
from typing import List, Dict, Optional, Any, Tuple
from datetime import datetime, date, timedelta
from collections import defaultdict

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from ..db.models import (
    Conversation, KnowledgeItem, KnowledgeEmbedding,
    KnowledgeReview, KnowledgeGap, DailyStats
)
from ..db.vector import VectorStore
from ..db.base import compute_embeddings, compute_embedding


class KnowledgeLearningPipeline:
    """
    知识自主学习流水线

    触发: 每天凌晨 02:00 (APScheduler 定时)
    输入: 过去 24h 的所有对话
    输出: 新 Q&A 对 + 审核队列 + 知识缺口 + 记忆更新
    """

    def __init__(self, db_factory, llm_router=None, persona_builder=None):
        self.db_factory = db_factory
        self.router = llm_router
        self.persona = persona_builder

    async def run(self, date_range: Tuple[date, date] = None) -> Dict[str, Any]:
        """
        执行完整学习流水线

        Returns:
            学习报告 dict
        """
        if date_range is None:
            yesterday = date.today() - timedelta(days=1)
            date_range = (yesterday, yesterday)

        logger.info(f"Knowledge Learning Pipeline starting for {date_range}")

        report = {
            "date": str(date_range[0]),
            "total_conversations": 0,
            "cleaned_conversations": 0,
            "questions_found": 0,
            "clusters_found": 0,
            "new_knowledge_auto": 0,
            "new_knowledge_pending": 0,
            "knowledge_gaps": 0,
            "memory_updates": 0,
        }

        async with self.db_factory() as db:
            # ── Step 0: 拉取对话 ──
            conversations = await self._fetch_conversations(db, date_range)
            report["total_conversations"] = len(conversations)
            logger.info(f"Step 0: Fetched {len(conversations)} conversations")

            if not conversations:
                return report

            # ── Step 1: 清洗 ──
            cleaned = self._clean(conversations)
            report["cleaned_conversations"] = len(cleaned)
            logger.info(f"Step 1: Cleaned → {len(cleaned)}")

            if not cleaned:
                return report

            # ── Step 2: 提取客户问题 ──
            questions = await self._extract_questions(cleaned)
            report["questions_found"] = len(questions)
            logger.info(f"Step 2: Extracted {len(questions)} questions")

            if not questions:
                return report

            # ── Step 3: 聚类 ──
            clusters = await self._cluster(questions)
            report["clusters_found"] = len(clusters)
            logger.info(f"Step 3: Clustered into {len(clusters)} groups")

            # ── Step 4: 生成 Q&A + 入库 ──
            new_knowledge = await self._generate_and_store(db, clusters, cleaned)
            report["new_knowledge_auto"] = len(new_knowledge.get("auto", []))
            report["new_knowledge_pending"] = len(new_knowledge.get("pending", []))

            # ── Step 5: 发现知识缺口 ──
            gaps = await self._find_gaps(db, cleaned)
            report["knowledge_gaps"] = len(gaps)

            # ── Step 6: 生成日报 ──
            await self._generate_report(db, date_range[0], report)

            await db.commit()

        logger.info(f"Pipeline complete: {report}")
        return report

    # ── 各步骤实现 ──────────────────────────────────

    async def _fetch_conversations(self, db: AsyncSession, date_range: Tuple[date, date]) -> List[Dict]:
        """拉取指定日期范围的对话"""
        start, end = date_range
        stmt = (
            select(Conversation)
            .where(
                Conversation.created_at >= start,
                Conversation.created_at < end + timedelta(days=1),
                Conversation.turn_count >= 3,           # 至少3轮
                Conversation.resolution_status != "closed",
            )
            .order_by(Conversation.created_at.desc())
            .limit(500)  # 单次最多500条
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()

        return [
            {
                "id": r.id,
                "user_id": r.user_id,
                "messages": r.messages or [],
                "intent": r.intent,
            }
            for r in rows
        ]

    def _clean(self, conversations: List[Dict]) -> List[Dict]:
        """清洗对话数据"""
        cleaned = []

        for conv in conversations:
            messages = conv.get("messages", [])

            # 提取客户消息
            user_msgs = []
            for m in messages:
                if m.get("role") != "user":
                    continue

                text = m.get("content", "").strip()

                # 过滤: 纯表情
                if len(text) < 2:
                    continue

                # 过滤: 仅"好的"/"谢谢"等 (对话应当都是用户问题而非简单确认)
                if text in ("好的", "谢谢", "OK", "嗯", "行", "好的呢", "ok", "嗯嗯", "知道了"):
                    continue

                # 过滤: 包含隐私信息
                if re.search(r'\d{11}', text):  # 手机号
                    continue

                user_msgs.append(text)

            if user_msgs:
                cleaned.append({
                    "id": conv["id"],
                    "user_id": conv["user_id"],
                    "messages": user_msgs,
                    "intent": conv.get("intent"),
                })

        return cleaned

    async def _extract_questions(self, cleaned: List[Dict]) -> List[Dict]:
        """
        从对话中提取规范化的客户问题

        返回: [{"text": "规范问题", "conv_id": "...", "original": "原始消息"}, ...]
        """
        questions = []

        for conv in cleaned:
            for msg_text in conv["messages"]:
                # 用 LLM 规范化问题 (cheap 模型)
                if self.router:
                    try:
                        normalized = await self._normalize_question(msg_text)
                    except Exception:
                        normalized = msg_text
                else:
                    normalized = msg_text

                questions.append({
                    "text": normalized,
                    "conv_id": conv["id"],
                    "original": msg_text,
                    "user_id": conv["user_id"],
                })

        return questions

    async def _normalize_question(self, text: str) -> str:
        """用 LLM 将问题标准化"""
        if not self.router:
            return text

        prompt = f"""将以下客户咨询标准化为一句简洁的问题（去掉语气词、保留核心意思）:

原文: "{text}"

标准问:"""

        from ..llm.base import LLMRequest
        try:
            result = await self.router.generate(
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=100,
                    temperature=0.2,
                    preferred_tag="cheap",
                ),
                "cheap",
            )
            return result.strip().strip('"').strip("'")
        except Exception:
            return text

    async def _cluster(self, questions: List[Dict]) -> List[Dict]:
        """聚类相似问题"""
        if not questions:
            return []

        # 计算向量
        texts = [q["text"] for q in questions]
        embeddings = compute_embeddings(texts)

        # 使用 HDBSCAN 或简单余弦相似度聚类
        clusters = self._cosine_cluster(texts, embeddings, threshold=0.78)

        # 过滤: 至少 3 个问题才算簇
        valid_clusters = []
        for cluster in clusters:
            if len(cluster["members"]) >= 3:
                # 找最具代表性的问题
                cluster["canonical"] = self._find_representative(cluster["members"])
                valid_clusters.append(cluster)

        return valid_clusters

    def _cosine_cluster(self, texts: List[str], embeddings: List, threshold: float = 0.78) -> List[Dict]:
        """简单余弦相似度聚类 (贪婪)"""
        import numpy as np

        n = len(texts)
        assigned = set()
        clusters = []

        emb_arr = np.array(embeddings)

        for i in range(n):
            if i in assigned:
                continue

            cluster_members = [texts[i]]
            cluster_indices = [i]
            assigned.add(i)

            # 找到所有相似的
            for j in range(i + 1, n):
                if j in assigned:
                    continue
                sim = np.dot(emb_arr[i], emb_arr[j])
                if sim >= threshold:
                    cluster_members.append(texts[j])
                    cluster_indices.append(j)
                    assigned.add(j)

            clusters.append({
                "members": cluster_members,
                "indices": cluster_indices,
                "size": len(cluster_members),
            })

        clusters.sort(key=lambda c: c["size"], reverse=True)
        return clusters

    def _find_representative(self, members: List[str]) -> str:
        """找簇中最具代表性的问题（最短且包含关键词的）"""
        if not members:
            return ""

        # 优先选中等长度的
        sorted_members = sorted(members, key=len)
        best = sorted_members[len(sorted_members) // 2]

        # 如果太短 (<5 chars), 选次短的
        if len(best) < 5 and len(sorted_members) > 1:
            best = sorted_members[1]

        return best

    async def _generate_and_store(self, db: AsyncSession, clusters: List[Dict], conversations: List[Dict]) -> Dict:
        """为每个簇生成 Q&A 并对并入库"""
        auto_applied = []
        pending_review = []

        # 构建 conv_id → messages 映射
        conv_map = {c["id"]: c for c in conversations}

        for cluster in clusters[:20]:  # 最多处理 20 个簇
            canonical_q = cluster["canonical"]

            # 检查是否与已有知识重复
            if await self._is_duplicate(db, canonical_q):
                continue

            # 从原始对话中提取最佳回答
            best_answer = await self._extract_best_answer(cluster, conv_map)

            if not best_answer:
                continue

            # 用 reasoning 模型优化回答
            if self.router:
                try:
                    polished = await self._polish_answer(canonical_q, best_answer)
                except Exception:
                    polished = best_answer
            else:
                polished = best_answer

            confidence = self._compute_confidence(cluster)

            item = {
                "question": canonical_q,
                "answer": polished,
                "confidence": confidence,
                "supporting_count": cluster["size"],
                "source_conv_ids": cluster.get("indices", []),
            }

            if confidence >= 0.85:
                # 高置信度 → 自动入库
                await self._auto_apply(db, item)
                auto_applied.append(item)
                logger.info(f"Auto-applied: {canonical_q[:50]}... (confidence: {confidence})")
            elif confidence >= 0.6:
                # 中置信度 → 审核队列
                await self._queue_review(db, item)
                pending_review.append(item)
                logger.info(f"Queued for review: {canonical_q[:50]}... (confidence: {confidence})")
            # 低置信度 → 丢弃

        return {"auto": auto_applied, "pending": pending_review}

    async def _is_duplicate(self, db: AsyncSession, question: str) -> bool:
        """检查是否与已有知识重复"""
        embedding = compute_embedding(question)

        distance = KnowledgeEmbedding.embedding.cosine_distance(embedding)
        stmt = (
            select(KnowledgeEmbedding.id)
            .where(distance < 0.15)  # cosine distance < 0.15 → 相似度 > 0.85
            .limit(1)
        )

        result = await db.execute(stmt)
        return result.first() is not None

    async def _extract_best_answer(self, cluster: Dict, conv_map: Dict) -> Optional[str]:
        """从原始对话中提取最佳回答"""
        # 获取簇中所有对话的原始消息
        # 取客服的回复（assistant 消息）
        candidate_answers = []

        for conv_id in cluster.get("source_conv_ids", [])[:10]:
            conv = conv_map.get(conv_id) if isinstance(conv_id, str) else None
            if conv:
                messages = conv.get("messages", [])
                for m in messages:
                    if m.get("role") == "assistant":
                        content = m.get("content", "")
                        if len(content) > 10:
                            candidate_answers.append(content)

        if not candidate_answers:
            return None

        # 选最长的回答（通常最详细）
        candidate_answers.sort(key=len, reverse=True)
        return candidate_answers[0]

    async def _polish_answer(self, question: str, raw_answer: str) -> str:
        """用 reasoning 模型优化回答"""
        if not self.router:
            return raw_answer

        prompt = f"""你是专业电商客服，优化以下回复使其更专业、准确、贴合人设。

客户问题: {question}
原始回复: {raw_answer}

优化要求:
1. 保持原始回复的核心信息
2. 语气自然，像真人
3. 不超过200字
4. 不确定的事情不承诺

优化后:"""

        from ..llm.base import LLMRequest
        try:
            result = await self.router.generate(
                LLMRequest(
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=400,
                    temperature=0.5,
                    preferred_tag="cheap",
                ),
                "cheap",
            )
            return result.strip()
        except Exception:
            return raw_answer

    def _compute_confidence(self, cluster: Dict) -> float:
        """计算置信度"""
        # 基于: 簇大小 + 成员一致性
        size = cluster.get("size", 1)

        # 簇越大越高
        size_score = min(1.0, size / 10.0)

        # 成员相似度
        members = cluster.get("members", [])
        if len(members) > 1:
            embeddings = compute_embeddings(members)
            import numpy as np
            arr = np.array(embeddings)
            sim_matrix = np.inner(arr, arr)
            # 排除对角线
            n = len(members)
            if n > 1:
                avg_sim = (sim_matrix.sum() - n) / (n * (n - 1))
                sim_score = avg_sim
            else:
                sim_score = 0.5
        else:
            sim_score = 0.3

        return round(0.4 * size_score + 0.6 * sim_score, 2)

    async def _auto_apply(self, db: AsyncSession, item: Dict):
        """高置信度自动入库"""
        import uuid

        kid = str(uuid.uuid4())
        # 写入知识库
        record = KnowledgeItem(
            id=kid,
            question=item["question"],
            answer=item["answer"],
            source="auto_learned",
            confidence=item["confidence"],
            status="active",
        )
        db.add(record)

        # 写入向量
        embedding = compute_embedding(item["question"] + "\n" + item["answer"])
        vid = str(uuid.uuid4())
        vec_record = KnowledgeEmbedding(
            id=vid,
            knowledge_id=kid,
            content=item["question"] + "\n" + item["answer"],
            embedding=embedding,
            content_type="qa",
        )
        db.add(vec_record)

        await db.flush()

    async def _queue_review(self, db: AsyncSession, item: Dict):
        """中置信度入审核队列"""
        import uuid

        review = KnowledgeReview(
            id=str(uuid.uuid4()),
            question=item["question"],
            answer=item["answer"],
            confidence=item["confidence"],
            supporting_count=item["supporting_count"],
            source_conversation_ids=item.get("source_conv_ids", []),
            status="pending",
        )
        db.add(review)
        await db.flush()

    async def _find_gaps(self, db: AsyncSession, conversations: List[Dict]) -> List[Dict]:
        """
        发现知识缺口
        找出 RAG 检索不够好的对话 → 标记为知识缺口
        """
        gaps = []

        for conv in conversations:
            # 检查标记了 escalate 的对话（可能是知识不足）
            # 实际上需要在对话处理时标记，这里做简化处理

            # 简单规则: 售后和投诉的对话如果量多，说明需要补充该方面知识
            if conv.get("intent") in ("aftersale", "other"):
                messages = conv.get("messages", [])
                for msg in messages:
                    text = msg if isinstance(msg, str) else msg.get("content", "")
                    if len(text) > 10 and len(text) < 200:
                        # 检查是否已有关联知识缺口
                        embedding = compute_embedding(text)
                        existing = await db.execute(
                            select(KnowledgeGap.id).where(
                                KnowledgeGap.status == "open"
                            ).limit(1)
                        )
                        # 简化处理：只记录频率高的
                        gaps.append({
                            "raw_question": text,
                            "conversation_id": conv["id"],
                        })

        # 去重 (简单)
        seen = set()
        unique_gaps = []
        for g in gaps:
            key = g["raw_question"][:50]
            if key not in seen:
                seen.add(key)
                unique_gaps.append(g)
                if len(unique_gaps) >= 10:
                    break

        # 写入数据库
        import uuid
        for g in unique_gaps[:5]:
            gap_record = KnowledgeGap(
                id=str(uuid.uuid4()),
                raw_question=g["raw_question"],
                frequency=gap_record.frequency if hasattr(gap_record, 'frequency') else 1,
                status="open",
            )
            try:
                db.add(gap_record)
            except:
                pass

        return unique_gaps

    async def _generate_report(self, db: AsyncSession, report_date: date, results: Dict):
        """生成日报"""
        import uuid

        stats = DailyStats(
            id=str(uuid.uuid4()),
            stat_date=report_date,
            shop_id="default",
            total_conversations=results.get("total_conversations", 0),
            total_messages=results.get("questions_found", 0),
        )
        db.add(stats)
        await db.flush()
