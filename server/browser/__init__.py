"""
Agent Browser 集成层
桥接 agent-browser MCP 服务和 Kefu Agent 工具系统
"""
from .adapter import BrowserAdapter, browser_adapter

__all__ = ["BrowserAdapter", "browser_adapter"]
