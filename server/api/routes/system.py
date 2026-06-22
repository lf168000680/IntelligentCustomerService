"""系统管理 API"""
from fastapi import APIRouter, HTTPException, Request
from typing import Optional

router = APIRouter()


def _state(request: Request):
    return request.app.state


@router.get("/status")
async def system_status(request: Request):
    s = _state(request)
    return {
        "server": "running",
        "llm_providers": s.llm_router.get_status() if s.llm_router else {},
        "message_bus": {"active_sessions": s.message_bus.get_active_count() if s.message_bus else 0},
        "adapters": await s.session_manager.health_check() if s.session_manager else {},
        "database": "connected",
    }


@router.post("/adapters/start")
async def start_adapter(platform: str = "taobao", shop_id: str = "default", request: Request = None):
    if not request.app.state.session_manager:
        raise HTTPException(status_code=503)
    adapter = await request.app.state.session_manager.start_adapter(platform=platform, shop_id=shop_id)
    if adapter:
        return {"status": "ok", "platform": platform, "shop_id": shop_id}
    raise HTTPException(status_code=500, detail="Failed to start adapter")


@router.post("/adapters/stop")
async def stop_adapter(platform: str = "taobao", shop_id: str = "default", request: Request = None):
    mgr = request.app.state.session_manager
    if not mgr:
        raise HTTPException(status_code=503)
    adapter = mgr.get_adapter(platform, shop_id)
    if adapter:
        await adapter.shutdown()
        return {"status": "ok"}
    raise HTTPException(status_code=404, detail="Adapter not found")


@router.post("/adapters/restart")
async def restart_adapter(platform: str = "taobao", shop_id: str = "default", request: Request = None):
    mgr = request.app.state.session_manager
    if not mgr:
        raise HTTPException(status_code=503)
    adapter = mgr.get_adapter(platform, shop_id)
    if adapter:
        ok = await adapter.restart()
        return {"status": "ok" if ok else "failed"}
    raise HTTPException(status_code=404, detail="Adapter not found")


@router.get("/logs")
async def get_recent_logs(lines: int = 100):
    return {"logs": []}
