"""
MCP (Model Context Protocol) 通用客户端 — Agent 自主接入外部工具

Kefu Agent 通过 MCP 协议连接任意外部工具服务:
- stdio 传输: 启动本地进程 (如 filesystem MCP Server)
- HTTP/SSE 传输: 连接远程服务

工作流:
1. 用户在 GUI 中添加 MCP Server 配置
2. Agent 启动时自动连接所有已启用的 MCP Server
3. 自动发现 Server 提供的工具列表
4. 将 MCP 工具注册到 ToolRegistry
5. Agent 调用工具时自动路由到对应 MCP Server
"""
import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path

from loguru import logger


@dataclass
class MCPServerConfig:
    """MCP Server 配置 (GUI 可管理)"""
    name: str                              # 显示名称, 如 "filesystem"
    command: str = ""                      # 启动命令, 如 "npx"
    args: List[str] = field(default_factory=list)   # 命令参数
    env: Dict[str, str] = field(default_factory=dict)  # 环境变量
    transport: str = "stdio"               # stdio | http
    url: str = ""                          # HTTP 传输时的 URL
    enabled: bool = True
    description: str = ""
    auto_restart: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name, "command": self.command, "args": self.args,
            "transport": self.transport, "url": self.url,
            "enabled": self.enabled, "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MCPServerConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class MCPTool:
    """MCP 工具 — 可注册到 ToolRegistry"""
    name: str
    description: str
    parameters: dict           # JSON Schema
    server_name: str

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": f"[mcp:{self.server_name}] {self.description}",
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict:
        return {
            "name": self.name,
            "description": f"[mcp:{self.server_name}] {self.description}",
            "input_schema": self.parameters,
        }


class MCPServerConnection:
    """单个 MCP Server 连接"""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.tools: List[MCPTool] = []
        self._request_id = 0
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> bool:
        """建立连接并发现工具"""
        if self.config.transport == "stdio":
            ok = await self._connect_stdio()
        else:
            ok = await self._connect_http()
        if ok:
            await self._discover_tools()
        return ok

    async def _connect_stdio(self) -> bool:
        try:
            cmd = [self.config.command] + self.config.args
            logger.info(f"MCP [{self.config.name}]: starting {' '.join(cmd)}")

            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True,
                env={**__import__('os').environ, **self.config.env},
            )

            resp = await self._rpc("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "kefu-agent", "version": "1.0.0"},
            })

            if resp and resp.get("result"):
                await self._notify("notifications/initialized", {})
                self._connected = True
                logger.info(f"MCP [{self.config.name}]: connected")
                return True
            return False
        except Exception as e:
            logger.error(f"MCP [{self.config.name}]: {e}")
            return False

    async def _connect_http(self) -> bool:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(f"{self.config.url}/initialize", json={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "kefu-agent", "version": "1.0.0"},
                })
                if r.status_code == 200:
                    self._connected = True
                    return True
        except Exception as e:
            logger.error(f"MCP [{self.config.name}]: HTTP {e}")
        return False

    async def _discover_tools(self):
        """发现 MCP Server 提供的工具"""
        resp = await self._rpc("tools/list", {})
        if resp and resp.get("result"):
            self.tools = []
            for t in resp["result"].get("tools", []):
                tool = MCPTool(
                    name=f"mcp_{self.config.name}_{t.get('name', 'unknown')}",
                    description=t.get("description", ""),
                    parameters=t.get("inputSchema", {}),
                    server_name=self.config.name,
                )
                self.tools.append(tool)
            logger.info(f"MCP [{self.config.name}]: {len(self.tools)} tools discovered")

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP 工具"""
        original = tool_name.replace(f"mcp_{self.config.name}_", "")
        resp = await self._rpc("tools/call", {"name": original, "arguments": arguments})
        if resp and resp.get("result"):
            return resp["result"]
        return {"error": str(resp.get("error", "unknown")) if resp else "no response"}

    async def _rpc(self, method: str, params: dict) -> Optional[dict]:
        """JSON-RPC 2.0 请求"""
        if not self.process or self.process.poll() is not None:
            if self.config.auto_restart and self.config.transport == "stdio":
                await self.connect()
            return None

        self._request_id += 1
        req = {"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}

        try:
            async with self._lock:
                self.process.stdin.write(json.dumps(req) + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline()
                return json.loads(line) if line else None
        except Exception as e:
            logger.error(f"MCP [{self.config.name}] RPC: {e}")
            self._connected = False
            return None

    async def _notify(self, method: str, params: dict):
        """JSON-RPC 通知 (无响应)"""
        if not self.process or self.process.poll() is not None:
            return
        try:
            async with self._lock:
                self.process.stdin.write(json.dumps(
                    {"jsonrpc": "2.0", "method": method, "params": params}
                ) + "\n")
                self.process.stdin.flush()
        except Exception:
            pass

    async def disconnect(self):
        self._connected = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    @property
    def is_connected(self) -> bool:
        return self._connected


class MCPClient:
    """
    MCP 客户端管理器 — Agent 自主接入 MCP 生态

    使用方式:
        client = MCPClient()
        client.configure([MCPServerConfig(name="filesystem", command="npx", ...)])
        await client.connect_all()
        # MCP 工具自动注册到 ToolRegistry
        await client.register_tools_to_agent()
        # Agent 现在可以调用 mcp_filesystem_read_file 等工具
    """

    def __init__(self, tool_registry=None):
        self.servers: Dict[str, MCPServerConnection] = {}
        self._configs: Dict[str, MCPServerConfig] = {}
        self._tool_registry = tool_registry   # 延迟注入
        self._config_file = Path("./config/mcp_servers.json")

    def configure(self, configs: List[MCPServerConfig]):
        for cfg in configs:
            self._configs[cfg.name] = cfg

    def add_server(self, config: MCPServerConfig):
        self._configs[config.name] = config
        self._save_config()

    def remove_server(self, name: str):
        self._configs.pop(name, None)
        self._save_config()

    async def connect_all(self) -> Dict[str, bool]:
        """连接所有启用的 MCP Server"""
        # 先从配置文件加载
        self._load_config()
        results = {}
        for name, config in self._configs.items():
            if not config.enabled:
                continue
            conn = MCPServerConnection(config)
            if await conn.connect():
                self.servers[name] = conn
                results[name] = True
            else:
                results[name] = False
        connected = sum(1 for v in results.values() if v)
        logger.info(f"MCP: {connected}/{len(results)} servers connected")
        return results

    async def register_tools_to_agent(self):
        """
        将所有 MCP 工具注册到 Agent 的 ToolRegistry

        这样 Agent 就可以像使用内置工具一样调用 MCP 工具
        """
        if not self._tool_registry:
            from ..tools import registry as tool_registry
            self._tool_registry = tool_registry

        count = 0
        for conn in self.servers.values():
            for mcp_tool in conn.tools:
                # 创建一个适配器工具，将 execute 委托给 MCP 调用
                adapter = _MCPToolAdapter(mcp_tool, conn)
                self._tool_registry.register(adapter)
                count += 1

        if count:
            logger.info(f"MCP: {count} tools registered to Agent")

    async def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """调用 MCP 工具 (自动路由)"""
        for name, conn in self.servers.items():
            if tool_name.startswith(f"mcp_{name}_"):
                return await conn.call_tool(tool_name, arguments)
        return {"error": f"MCP tool not found: {tool_name}"}

    async def list_all_tools(self) -> List[MCPTool]:
        tools = []
        for conn in self.servers.values():
            tools.extend(conn.tools)
        return tools

    async def disconnect_all(self):
        for conn in self.servers.values():
            await conn.disconnect()
        self.servers.clear()

    async def health_check(self) -> dict:
        status = {}
        for name, conn in self.servers.items():
            status[name] = {"connected": conn.is_connected, "tools": len(conn.tools)}
        for name, cfg in self._configs.items():
            if name not in status:
                status[name] = {"connected": False, "tools": 0, "enabled": cfg.enabled}
        return status

    def _save_config(self):
        """持久化 MCP 配置到 JSON 文件"""
        try:
            self._config_file.parent.mkdir(parents=True, exist_ok=True)
            configs = [c.to_dict() for c in self._configs.values()]
            self._config_file.write_text(json.dumps(configs, indent=2, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"Failed to save MCP config: {e}")

    def _load_config(self):
        """从 JSON 文件加载 MCP 配置"""
        if self._config_file.exists():
            try:
                configs = json.loads(self._config_file.read_text())
                for item in configs:
                    cfg = MCPServerConfig.from_dict(item)
                    if cfg.name not in self._configs:
                        self._configs[cfg.name] = cfg
            except Exception as e:
                logger.warning(f"Failed to load MCP config: {e}")

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self.servers.values() if c.is_connected)


class _MCPToolAdapter:
    """
    将 MCPTool 适配为 ToolRegistry 兼容的工具对象

    实现 BaseTool 的核心接口: name, description, parameters, execute()
    """
    def __init__(self, mcp_tool: MCPTool, connection: MCPServerConnection):
        self.name = mcp_tool.name
        self.description = mcp_tool.description
        self.parameters = mcp_tool.parameters
        self.category = "mcp"
        self.tags = ["mcp", mcp_tool.server_name]
        self._mcp_tool = mcp_tool
        self._conn = connection

    async def execute(self, **kwargs) -> Any:
        from ..tools.base import ToolResult
        result = await self._conn.call_tool(self.name, kwargs)
        if "error" in result:
            return ToolResult.fail(result["error"])
        content = result.get("content", [])
        if isinstance(content, list) and content:
            text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
            return ToolResult.ok(text)
        return ToolResult.ok(result)


# 全局单例
mcp_client = MCPClient()
