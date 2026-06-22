"""
Anthropic Messages API — 原生实现
支持 Anthropic 官方 API 及兼容中继 (如 OneAPI, LiteLLM 等)
"""
from typing import AsyncIterator, List, Dict, Any, Optional

from .base import BaseLLMProvider, LLMRequest, ModelConfig


class AnthropicProvider(BaseLLMProvider):
    """Anthropic Messages API (claude-sonnet-4-6, claude-opus-4-8, etc.)"""

    provider_type = "anthropic"

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        import anthropic

        extra = config.extra_config or {}
        custom_headers = config.headers or {}

        # ── 构建客户端参数 ──
        client_kwargs: Dict[str, Any] = {
            "api_key": config.api_key,
            "max_retries": extra.get("max_retries", 3),
        }

        # 支持自定义 api_base (Anthropic 兼容中继 / 中转站)
        if config.api_base:
            client_kwargs["base_url"] = config.api_base

        # 支持自定义 headers (中继认证、自定义追踪等)
        if custom_headers:
            client_kwargs["default_headers"] = custom_headers

        # 其他客户端级参数
        if extra.get("timeout"):
            client_kwargs["timeout"] = extra["timeout"]

        self.client = anthropic.AsyncAnthropic(**client_kwargs)

        # ── 提取 API 调用级额外参数 (透传到 messages.create / stream) ──
        _client_keys = {"headers", "max_retries", "timeout"}
        self.api_extra = {k: v for k, v in extra.items() if k not in _client_keys}

    @classmethod
    def supports_tools(cls) -> bool:
        """Anthropic Messages API 原生支持 tool use"""
        return True

    async def chat(self, request: LLMRequest) -> str:
        messages = self._convert_messages(request.messages)
        system = request.system_prompt or None

        kwargs: Dict[str, Any] = {}
        if system:
            kwargs["system"] = system

        # 合并 extra_config 中的 API 参数
        kwargs.update(self.api_extra)

        # 工具支持: 若请求带 tools 则透传
        if request.tools:
            kwargs["tools"] = request.tools

        resp = await self.client.messages.create(
            model=self.model_id,
            max_tokens=request.max_tokens or self.config.max_tokens,
            messages=messages,
            temperature=request.temperature if request.temperature is not None else self.config.temperature,
            **kwargs,
        )
        return resp.content[0].text

    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        messages = self._convert_messages(request.messages)
        system = request.system_prompt or None

        kwargs: Dict[str, Any] = {}
        if system:
            kwargs["system"] = system

        # 合并 extra_config 中的 API 参数
        kwargs.update(self.api_extra)

        # 工具支持: 若请求带 tools 则透传
        if request.tools:
            kwargs["tools"] = request.tools

        async with self.client.messages.stream(
            model=self.model_id,
            max_tokens=request.max_tokens or self.config.max_tokens,
            messages=messages,
            temperature=request.temperature if request.temperature is not None else self.config.temperature,
            **kwargs,
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def count_tokens(self, messages: List[Dict]) -> int:
        try:
            resp = await self.client.messages.count_tokens(
                model=self.model_id,
                messages=messages,
            )
            return resp.input_tokens
        except Exception:
            return await super().count_tokens(messages)

    def _convert_messages(self, messages: List[Dict]) -> List[Dict]:
        """
        OpenAI format → Anthropic format
        Anthropic 要求 roles 交替，不允许连续同角色
        """
        converted = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")

            # Anthropic 不支持 system role 在 messages 里
            if role == "system":
                continue
            if role == "assistant":
                role = "assistant"
            else:
                role = "user"

            # 合并连续同角色消息
            if converted and converted[-1]["role"] == role:
                prev_content = converted[-1]["content"]
                if isinstance(prev_content, str) and isinstance(content, str):
                    converted[-1]["content"] = prev_content + "\n" + content
                else:
                    converted.append({"role": role, "content": content})
            else:
                converted.append({"role": role, "content": content})

        return converted
