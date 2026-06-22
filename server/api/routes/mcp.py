"""
MCP 管理 API — 动态添加/删除 MCP Server, Agent 自主接入外部工具
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

router = APIRouter()


class MCPServerRequest(BaseModel):
    name: str
    command: str = "npx"
    args: List[str] = []
    transport: str = "stdio"
    url: str = ""
    enabled: bool = True
    description: str = ""


@router.get("/servers")
async def list_servers():
    """列出所有 MCP Server"""
    try:
        from ...mcp import mcp_client

        servers = []
        for name, cfg in mcp_client._configs.items():
            conn = mcp_client.servers.get(name)
            servers.append({
                "name": name,
                "command": cfg.command,
                "args": cfg.args,
                "transport": cfg.transport,
                "url": cfg.url,
                "enabled": cfg.enabled,
                "description": cfg.description,
                "connected": conn.is_connected if conn else False,
                "tools_count": len(conn.tools) if conn else 0,
                "tools": [t.name for t in (conn.tools if conn else [])],
            })
        return {"servers": servers}
    except Exception as e:
        return {"servers": [], "error": str(e)}


@router.post("/servers")
async def add_server(req: MCPServerRequest):
    """添加 MCP Server (持久化到 config/mcp_servers.json)"""
    try:
        from ...mcp import mcp_client, MCPServerConfig

        cfg = MCPServerConfig(
            name=req.name, command=req.command, args=req.args,
            transport=req.transport, url=req.url,
            enabled=req.enabled, description=req.description,
        )
        mcp_client.add_server(cfg)
        return {"status": "ok", "name": req.name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/servers/{name}")
async def delete_server(name: str):
    """删除 MCP Server"""
    try:
        from ...mcp import mcp_client

        conn = mcp_client.servers.get(name)
        if conn:
            await conn.disconnect()
            del mcp_client.servers[name]
        mcp_client.remove_server(name)
        return {"status": "deleted", "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{name}/connect")
async def connect_server(name: str):
    """连接指定 MCP Server 并注册工具"""
    try:
        from ...mcp import mcp_client, MCPServerConnection

        cfg = mcp_client._configs.get(name)
        if not cfg:
            raise HTTPException(status_code=404, detail=f"Server not found: {name}")

        conn = MCPServerConnection(cfg)
        if await conn.connect():
            mcp_client.servers[name] = conn
            await mcp_client.register_tools_to_agent()
            return {"status": "connected", "name": name, "tools": len(conn.tools)}
        raise HTTPException(status_code=500, detail="Connection failed")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/servers/{name}/disconnect")
async def disconnect_server(name: str):
    """断开 MCP Server"""
    try:
        from ...mcp import mcp_client

        conn = mcp_client.servers.get(name)
        if conn:
            await conn.disconnect()
            del mcp_client.servers[name]
        return {"status": "disconnected", "name": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tools")
async def list_all_mcp_tools():
    """列出所有 MCP 工具"""
    try:
        from ...mcp import mcp_client

        tools = await mcp_client.list_all_tools()
        return {
            "tools": [{"name": t.name, "description": t.description, "server": t.server_name} for t in tools],
            "count": len(tools),
        }
    except Exception as e:
        return {"tools": [], "error": str(e)}


@router.get("/health")
async def health():
    """MCP 健康检查"""
    try:
        from ...mcp import mcp_client
        return {
            "health": await mcp_client.health_check(),
            "connected_count": mcp_client.connected_count,
            "total_servers": len(mcp_client._configs),
        }
    except Exception as e:
        return {"error": str(e)}
