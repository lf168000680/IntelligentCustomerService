"""
Browser API — agent-browser Skill (本地 CLI 工具)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class BrowserActionRequest(BaseModel):
    action: str  # navigate | screenshot | extract | search | check_policy
    url: Optional[str] = None
    query: Optional[str] = None
    platform: str = "taobao"
    selector: Optional[str] = None


@router.post("/action")
async def browser_action(req: BrowserActionRequest):
    """执行浏览器操作 (通过 agent-browser CLI)"""
    try:
        from ...browser import browser_adapter

        if not browser_adapter.available:
            raise HTTPException(
                status_code=503,
                detail="agent-browser skill not installed. Run: npm install -g agent-browser"
            )

        action_map = {
            "navigate": lambda: browser_adapter.navigate(req.url, req.selector or "body"),
            "screenshot": lambda: browser_adapter.screenshot(req.url, req.selector or "body"),
            "extract": lambda: browser_adapter.extract(req.url, req.selector or "body"),
            "search": lambda: browser_adapter.search_product(req.query or "", req.platform),
            "check_policy": lambda: browser_adapter.check_policy(req.platform),
        }

        handler = action_map.get(req.action)
        if not handler:
            raise HTTPException(status_code=400, detail=f"Unknown action: {req.action}")

        result = await handler()
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "screenshot_path": result.screenshot_path,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def browser_status():
    """Browser Skill 状态"""
    try:
        from ...browser import browser_adapter
        return {
            "available": browser_adapter.available,
            "type": "local_skill_cli",
            "screenshots_dir": str(browser_adapter._screenshots_dir),
        }
    except Exception as e:
        return {"error": str(e), "available": False}
