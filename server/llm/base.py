"""
LLM 抽象基类 + 统一数据结构
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, List, Dict, Any


@dataclass
class ModelConfig:
    """单个模型配置 — 跨厂商，自由字符串标识 provider"""
    name: str
    provider: str                          # 自由字符串: "anthropic", "openai", "openai_compat", "custom", or any string
    model_id: str
    api_key: str
    api_base: Optional[str] = None         # 自定义 endpoint URL (中转站/relay)
    temperature: float = 0.7
    max_tokens: int = 4096
    weight: int = 100
    enabled: bool = True
    tags: List[str] = field(default_factory=lambda: ["default"])
    headers: Optional[dict] = None         # 自定义 HTTP headers (中转服务)
    extra_config: Optional[dict] = None    # 厂商特定额外配置


@dataclass
class LLMRequest:
    """统一请求对象 — 跨厂商"""
    messages: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    tools: Optional[List[Dict]] = None
    stream: bool = False

    # 路由提示
    preferred_provider: Optional[str] = None   # anthropic | openai | openai_compat
    preferred_tag: Optional[str] = None        # fast | cheap | reasoning | default


class BaseLLMProvider(ABC):
    """所有 LLM 厂商的抽象基类"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.model_id = config.model_id

    @abstractmethod
    async def chat(self, request: LLMRequest) -> str:
        """非流式聊天"""
        ...

    @abstractmethod
    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        """流式聊天"""
        ...

    async def supports_tools(self) -> bool:
        """该模型是否支持原生 tool calling。默认返回 False，子类按需覆盖。"""
        return False

    async def count_tokens(self, messages: List[Dict]) -> int:
        """Token 计数 (默认估算)"""
        total = 0
        for m in messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content) // 2  # 中文约 1 token = 2 chars
            elif isinstance(content, list):
                total += sum(len(c.get("text", "")) // 2 for c in content if isinstance(c, dict))
        return max(1, total)

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            await self.chat(LLMRequest(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            ))
            return True
        except Exception:
            return False
