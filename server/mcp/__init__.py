"""
MCP (Model Context Protocol) 客户端
为 Kefu Agent 提供外部工具和服务的统一接入
"""
from .client import MCPClient, MCPServerConfig, mcp_client

__all__ = ["MCPClient", "MCPServerConfig", "mcp_client"]
