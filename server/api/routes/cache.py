"""
缓存管理 API — 查看命中率、手动失效、预热
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter()


class CacheWarmupRequest(BaseModel):
    faqs: List[Dict[str, str]]  # [{"question": "...", "answer": "..."}]


@router.get("/stats")
async def get_stats():
    """获取缓存统计"""
    try:
        from ...cache import cache_manager
        return cache_manager.get_summary()
    except Exception as e:
        return {"error": str(e)}


@router.get("/hit-rate")
async def get_hit_rate():
    """获取缓存命中率"""
    try:
        from ...cache import cache_manager
        return {
            "overall_hit_rate": cache_manager.tracker.overall_hit_rate,
            "L1": {
                "size": cache_manager.L1.size,
                "hit_rate": cache_manager.L1.hit_rate,
                "hits": cache_manager.L1.hits,
                "misses": cache_manager.L1.misses,
            },
            "L3": {
                "size": cache_manager.L3.size,
                "hit_rate": cache_manager.L3.hit_rate,
                "hits": cache_manager.L3.hits,
                "misses": cache_manager.L3.misses,
            },
            "enabled": cache_manager.enabled,
            "estimated_cost_saved": round(cache_manager.tracker.llm_saved, 2),
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/invalidate")
async def invalidate_cache(
    message: Optional[str] = None,
    intent: Optional[str] = None,
    knowledge_id: Optional[str] = None,
    clear_all: bool = False,
):
    """缓存失效"""
    try:
        from ...cache import cache_manager

        if clear_all:
            cache_manager.clear_all()
            return {"status": "ok", "message": "All cache cleared"}

        await cache_manager.invalidate(
            message=message,
            intent=intent,
            knowledge_id=knowledge_id,
        )
        return {
            "status": "ok",
            "invalidated": {
                "message": message,
                "intent": intent,
                "knowledge_id": knowledge_id,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/warm-up")
async def warm_up(req: CacheWarmupRequest):
    """缓存预热"""
    try:
        from ...cache import cache_manager

        await cache_manager.warm_up(req.faqs)
        return {
            "status": "ok",
            "warmed": len(req.faqs),
            "L1_size": cache_manager.L1.size,
            "L3_size": cache_manager.L3.size,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/toggle")
async def toggle_cache():
    """切换缓存开关"""
    try:
        from ...cache import cache_manager

        cache_manager.enabled = not cache_manager.enabled
        return {"enabled": cache_manager.enabled}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/top")
async def get_top_cached(limit: int = 20):
    """获取命中次数最多的缓存条目"""
    try:
        from ...cache import cache_manager

        entries = sorted(
            cache_manager.L3._entries,
            key=lambda e: e.hit_count,
            reverse=True,
        )[:limit]

        return {
            "top_entries": [
                {
                    "question": e.question[:100],
                    "hit_count": e.hit_count,
                    "intent": e.intent,
                    "created_at": e.created_at,
                }
                for e in entries
            ]
        }
    except Exception as e:
        return {"error": str(e)}
