"""
系统管理 API
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any



router = APIRouter()


@router.get("/status")
async def system_status():
    """系统全维度状态"""
    return {
        "server": "running",
        "llm_providers": main.llm_router.get_status() if main.llm_router else {},
        "message_bus": {
            "active_sessions": main.message_bus.get_active_count() if main.message_bus else 0,
        },
        "adapters": await main.session_manager.health_check() if main.session_manager else {},
        "database": "connected" if main.db_engine else "disconnected",
    }


@router.post("/adapters/start")
async def start_adapter(platform: str = "taobao", shop_id: str = "default"):
    """启动适配器"""
    if not main.session_manager:
        raise HTTPException(status_code=503)

    adapter = await main.session_manager.start_adapter(
        platform=platform,
        shop_id=shop_id,
    )
    if adapter:
        return {"status": "ok", "platform": platform, "shop_id": shop_id}
    raise HTTPException(status_code=500, detail="Failed to start adapter")


@router.post("/adapters/stop")
async def stop_adapter(platform: str = "taobao", shop_id: str = "default"):
    """停止适配器"""
    if not main.session_manager:
        raise HTTPException(status_code=503)

    adapter = main.session_manager.get_adapter(platform, shop_id)
    if adapter:
        await adapter.shutdown()
        return {"status": "ok", "platform": platform, "shop_id": shop_id}
    raise HTTPException(status_code=404, detail="Adapter not found")


@router.post("/adapters/restart")
async def restart_adapter(platform: str = "taobao", shop_id: str = "default"):
    """重启适配器"""
    if not main.session_manager:
        raise HTTPException(status_code=503)

    adapter = main.session_manager.get_adapter(platform, shop_id)
    if adapter:
        success = await adapter.restart()
        return {"status": "ok" if success else "failed"}
    raise HTTPException(status_code=404, detail="Adapter not found")


@router.get("/logs")
async def get_recent_logs(lines: int = 100):
    """获取最近日志"""
    return {"logs": [], "message": "Log API not yet implemented"}
