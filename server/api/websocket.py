"""
WebSocket 实时推送 — 会话更新、告警通知
"""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import json
import asyncio

router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self._id_counter = 0

    async def connect(self, websocket: WebSocket) -> str:
        await websocket.accept()
        self._id_counter += 1
        conn_id = f"ws_{self._id_counter}"
        self.active_connections[conn_id] = websocket
        return conn_id

    def disconnect(self, conn_id: str):
        self.active_connections.pop(conn_id, None)

    async def broadcast(self, data: dict):
        """广播消息到所有连接"""
        dead = []
        for conn_id, ws in self.active_connections.items():
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(conn_id)
        for conn_id in dead:
            self.disconnect(conn_id)

    async def send(self, conn_id: str, data: dict):
        """发送消息到指定连接"""
        ws = self.active_connections.get(conn_id)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(conn_id)

    @property
    def count(self) -> int:
        return len(self.active_connections)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 连接端点"""
    conn_id = await manager.connect(websocket)
    try:
        # 发送欢迎消息
        await websocket.send_json({
            "type": "connected",
            "conn_id": conn_id,
            "message": "已连接到 Kefu 实时数据流",
        })

        # 保持连接，接收客户端心跳
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        manager.disconnect(conn_id)
    except Exception:
        manager.disconnect(conn_id)


# 全局广播函数 (其他模块调用)
async def broadcast_event(event_type: str, data: dict):
    """广播事件"""
    await manager.broadcast({
        "type": event_type,
        "data": data,
    })
