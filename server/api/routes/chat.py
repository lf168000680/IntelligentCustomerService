"""会话相关 API"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    user_id: str = "test_user"
    user_name: Optional[str] = None
    platform: str = "test"
    shop_id: str = "default"
    conversation_id: Optional[str] = None
    product: Optional[Dict] = None


class ChatResponse(BaseModel):
    reply: str
    intent: Optional[str] = None
    escalate: bool = False
    metadata: Dict[str, Any] = {}


@router.post("/send", response_model=ChatResponse)
async def send_message(req: ChatRequest, request: Request):
    engine = request.app.state.engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    result = await engine.process(req.message, {
        "user_id": req.user_id, "user_name": req.user_name or req.user_id,
        "platform": req.platform, "shop_id": req.shop_id,
        "conversation_id": req.conversation_id, "product": req.product, "history": [],
    })
    return ChatResponse(reply=result["reply"], intent=result.get("intent"),
                        escalate=result.get("escalate", False), metadata=result.get("metadata", {}))


@router.post("/test-persona")
async def test_persona(req: ChatRequest, request: Request):
    engine = request.app.state.engine
    if not engine:
        raise HTTPException(status_code=503, detail="Engine not ready")
    return {"reply": await engine.test_persona(req.message)}


@router.get("/sessions")
async def get_active_sessions(request: Request):
    bus = request.app.state.message_bus
    if not bus:
        return {"sessions": [], "count": 0}
    sessions = []
    for key, session in bus.active_sessions.items():
        sessions.append({"key": key, "user_name": session.get("user_name", ""),
                         "platform": session.get("platform", ""),
                         "turn_count": len([m for m in session.get("history", []) if m.get("role") == "user"]),
                         "last_active": session.get("last_active")})
    return {"count": len(sessions), "sessions": sessions}
