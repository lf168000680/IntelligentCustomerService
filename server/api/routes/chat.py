"""
会话相关 API
"""
from fastapi import APIRouter, HTTPException
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
async def send_message(req: ChatRequest):
    """发送消息，获取 AI 回复"""
    if not main.engine:
        raise HTTPException(status_code=503, detail="Engine not ready")

    context = {
        "user_id": req.user_id,
        "user_name": req.user_name or req.user_id,
        "platform": req.platform,
        "shop_id": req.shop_id,
        "conversation_id": req.conversation_id,
        "product": req.product,
        "history": [],  # 从 DB 加载
    }

    result = await main.engine.process(req.message, context)

    return ChatResponse(
        reply=result["reply"],
        intent=result.get("intent"),
        escalate=result.get("escalate", False),
        metadata=result.get("metadata", {}),
    )


@router.post("/test-persona")
async def test_persona(req: ChatRequest):
    """人设测试 (无知识库)"""
    if not main.engine:
        raise HTTPException(status_code=503, detail="Engine not ready")

    reply = await main.engine.test_persona(req.message)
    return {"reply": reply}


@router.get("/sessions")
async def get_active_sessions():
    """获取活跃会话列表"""
    if not main.message_bus:
        return {"sessions": []}

    sessions = []
    for key, session in main.message_bus.active_sessions.items():
        sessions.append({
            "key": key,
            "user_name": session.get("user_name", ""),
            "platform": session.get("platform", ""),
            "turn_count": len([m for m in session.get("history", [])
                               if m.get("role") == "user"]),
            "last_active": session.get("last_active"),
        })

    return {
        "count": len(sessions),
        "sessions": sessions,
    }
