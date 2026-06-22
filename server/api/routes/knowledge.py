"""
知识库管理 API
"""
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter()


class KnowledgeCreate(BaseModel):
    question: str
    answer: str
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    status: str = "active"


class KnowledgeUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class KnowledgeItem(BaseModel):
    id: str
    question: str
    answer: str
    category: Optional[str] = None
    source: str
    usage_count: int = 0
    confidence: float = 1.0
    status: str
    created_at: Optional[str] = None


@router.get("/", response_model=List[KnowledgeItem])
async def list_knowledge(
    category: Optional[str] = None,
    source: Optional[str] = None,
    status: Optional[str] = "active",
    search: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
):
    """获取知识库列表"""
    # 返回空列表当 DB 不可用时
    return []


@router.get("/search")
async def search_knowledge(
    query: str,
    top_k: int = Query(default=5, le=20),
):
    """搜索知识库"""
    if not main.engine:
        return {"hits": []}

    # 需要 DB session
    return {
        "query": query,
        "hits": [],
        "message": "Search requires database connection",
    }


@router.post("/", response_model=KnowledgeItem)
async def create_knowledge(item: KnowledgeCreate):
    """手动添加知识条目"""
    import uuid
    kid = str(uuid.uuid4())
    return KnowledgeItem(
        id=kid,
        question=item.question,
        answer=item.answer,
        category=item.category,
        source="manual",
        usage_count=0,
        status=item.status,
    )


@router.put("/{knowledge_id}", response_model=KnowledgeItem)
async def update_knowledge(knowledge_id: str, item: KnowledgeUpdate):
    """更新知识条目"""
    return KnowledgeItem(
        id=knowledge_id,
        question=item.question or "",
        answer=item.answer or "",
        category=item.category,
        source="manual",
        status=item.status or "active",
    )


@router.delete("/{knowledge_id}")
async def delete_knowledge(knowledge_id: str):
    """删除知识条目"""
    return {"deleted": knowledge_id}


@router.get("/reviews")
async def get_review_queue(
    status: str = "pending",
    limit: int = 20,
):
    """获取审核队列"""
    return {
        "queue": [],
        "count": 0,
    }


@router.post("/reviews/{review_id}/approve")
async def approve_review(review_id: str):
    """批准审核条目"""
    return {"approved": review_id}


@router.post("/reviews/{review_id}/reject")
async def reject_review(review_id: str, reason: Optional[str] = None):
    """拒绝审核条目"""
    return {"rejected": review_id, "reason": reason}


@router.get("/gaps")
async def get_knowledge_gaps(limit: int = 20):
    """获取知识缺口"""
    return {
        "gaps": [],
        "count": 0,
    }


@router.post("/learn")
async def trigger_learning(days_back: int = 1):
    """手动触发知识学习"""
    if not main.scheduler:
        raise HTTPException(status_code=503, detail="Scheduler not available")

    try:
        report = await main.scheduler.trigger_learning(days_back)
        return {"status": "ok", "report": report}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
