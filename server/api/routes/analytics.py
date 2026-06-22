"""
数据统计 API
"""
from fastapi import APIRouter, Query
from typing import Optional

router = APIRouter()


@router.get("/overview")
async def get_overview():
    """获取数据概览"""
    from server import main

    return {
        "llm_status": main.llm_router.get_status() if main.llm_router else {},
        "active_sessions": main.message_bus.get_active_count() if main.message_bus else 0,
        "adapters": await main.session_manager.health_check() if main.session_manager else {},
        "timestamp": None,
    }


@router.get("/daily")
async def get_daily_stats(days: int = Query(default=7, le=30)):
    """获取日报数据"""
    return {
        "days": days,
        "stats": [],
        "message": "Requires database connection for historical data",
    }


@router.get("/top-issues")
async def get_top_issues(limit: int = 10):
    """获取热门问题"""
    return {
        "top_issues": [],
        "message": "Requires database connection",
    }


@router.get("/model-usage")
async def get_model_usage():
    """获取各模型使用统计"""
    from server import main
    if not main.llm_router:
        return {"models": []}

    return {
        "models": main.llm_router.get_status(),
    }
