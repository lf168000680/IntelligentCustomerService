"""
OpenAI 兼容协议 — 统配所有兼容 API 的通用 Provider

支持:
- OpenAI 官方 API
- DeepSeek API
- 豆包 (Doubao) / 火山引擎 Ark
- 通义千问 (Qwen) / 阿里云 DashScope
- GLM (智谱) / BigModel
- Groq
- 任意 API 中转站 / Relay (自定义 base_url + headers 鉴权)
- 本地 vLLM / Ollama / LM Studio / llama.cpp server
- 任何兼容 /v1/chat/completions 或 /v1/responses 的 API

使用方式:
    config = ModelConfig(
        provider="openai_compat",
        model_id="deepseek-chat",
        api_key="sk-xxx",
        api_base="https://api.deepseek.com/v1",
        headers={"X-Custom-Header": "value"},
        extra_config={
            "timeout": 120,
            "max_retries": 5,
            "response_format": {"type": "json_object"},
            "stop": ["END"],
            "top_p": 0.9,
            "extra_body": {"custom_param": "value"},
        },
    )
    provider = UniversalProvider(config)
    reply = await provider.chat(request)               # /v1/chat/completions
    reply = await provider.responses(request)          # /v1/responses (if supported)
"""
from typing import AsyncIterator, List, Dict, Optional, Any

from .base import BaseLLMProvider, LLMRequest, ModelConfig


class UniversalProvider(BaseLLMProvider):
    """Universal provider for ANY OpenAI-compatible API.

    Single class handles every /v1/chat/completions-compatible service:
      - Official OpenAI, DeepSeek, Doubao, Qwen, GLM, Groq
      - Relay/中转站 services (custom base_url + auth headers)
      - Local vLLM, Ollama, LM Studio, etc.

    Also supports the newer /v1/responses endpoint when available.
    """

    provider_type = "openai_compat"

    # ------------------------------------------------------------------
    # Constructor
    # ------------------------------------------------------------------

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        from openai import AsyncOpenAI

        extra: dict = config.extra_config or {}

        # --- Client-level settings (overridable per provider) ---
        timeout: float = float(extra.get("timeout", 60.0))
        max_retries: int = int(extra.get("max_retries", 3))

        # --- Custom HTTP headers (for relay/中转站 auth: X-Api-Key, etc.) ---
        self.custom_headers: Dict[str, str] = dict(config.headers or {})

        # --- API base URL (normalize: no trailing slash) ---
        api_base: Optional[str] = config.api_base
        if api_base:
            api_base = api_base.rstrip("/")

        # --- Build AsyncOpenAI client ---
        client_kwargs: Dict[str, Any] = {
            "api_key": config.api_key,
            "max_retries": max_retries,
            "timeout": timeout,
        }
        if api_base:
            client_kwargs["base_url"] = api_base
        if self.custom_headers:
            client_kwargs["default_headers"] = self.custom_headers

        self.client = AsyncOpenAI(**client_kwargs)

        # --- Per-request defaults from extra_config ---
        self._response_format: Optional[Dict] = extra.get("response_format")
        self._stop: Optional[List[str]] = extra.get("stop")
        self._top_p: Optional[float] = extra.get("top_p")
        self._frequency_penalty: Optional[float] = extra.get("frequency_penalty")
        self._presence_penalty: Optional[float] = extra.get("presence_penalty")
        self._extra_body: Optional[Dict] = extra.get("extra_body")

        # --- Responses API capability ---
        self._use_responses_default: bool = bool(extra.get("use_responses", False))

        self._log_init(config, api_base)

    def _log_init(self, config: ModelConfig, api_base: Optional[str]) -> None:
        """Log provider initialization details for debugging."""
        from loguru import logger
        hdr_keys = list(self.custom_headers.keys())
        logger.debug(
            f"UniversalProvider [{config.name}]: model={config.model_id}, "
            f"base={api_base or 'OpenAI default'}, "
            f"headers={hdr_keys or 'none'}, "
            f"responses_api={self._use_responses_default}"
        )

    # ------------------------------------------------------------------
    # Chat Completions (/v1/chat/completions)
    # ------------------------------------------------------------------

    async def chat(self, request: LLMRequest) -> str:
        """Non-streaming chat via /v1/chat/completions."""
        messages = self._build_messages(request)
        kwargs = self._build_chat_kwargs(request, messages, stream=False)

        resp = await self.client.chat.completions.create(**kwargs)
        return self._extract_content(resp)

    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        """Streaming chat via /v1/chat/completions."""
        messages = self._build_messages(request)
        kwargs = self._build_chat_kwargs(request, messages, stream=True)

        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            delta = self._extract_delta(chunk)
            if delta:
                yield delta

    # ------------------------------------------------------------------
    # Responses API (/v1/responses) — newer OpenAI endpoint
    # ------------------------------------------------------------------

    async def responses(
        self,
        request: LLMRequest,
        instructions: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> str:
        """Non-streaming via /v1/responses (if provider supports it).

        Falls back gracefully if the endpoint is not available.
        """
        kwargs = self._build_responses_kwargs(request, instructions, tools, stream=False)
        resp = await self.client.responses.create(**kwargs)
        return self._extract_response_text(resp)

    async def stream_responses(
        self,
        request: LLMRequest,
        instructions: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
    ) -> AsyncIterator[str]:
        """Streaming via /v1/responses (if provider supports it)."""
        kwargs = self._build_responses_kwargs(request, instructions, tools, stream=True)

        stream = await self.client.responses.create(**kwargs)
        async for event in stream:
            if event.type == "response.output_text.delta":
                if event.delta:
                    yield event.delta

    # ------------------------------------------------------------------
    # Message building
    # ------------------------------------------------------------------

    def _build_messages(self, request: LLMRequest) -> List[Dict[str, Any]]:
        """Build the messages list from an LLMRequest."""
        messages: List[Dict[str, Any]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        return messages

    # ------------------------------------------------------------------
    # Chat-completions kwargs builder (single source of truth)
    # ------------------------------------------------------------------

    def _build_chat_kwargs(
        self,
        request: LLMRequest,
        messages: List[Dict[str, Any]],
        stream: bool,
    ) -> Dict[str, Any]:
        """Build kwargs dict for client.chat.completions.create().

        Uses OpenAI SDK naming; extra_config overrides are merged in.
        """
        kwargs: Dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
        }

        # Max tokens
        max_tok = request.max_tokens or self.config.max_tokens
        if max_tok:
            kwargs["max_tokens"] = max_tok

        # Temperature
        temperature = request.temperature if request.temperature is not None else self.config.temperature
        kwargs["temperature"] = temperature

        # Streaming
        if stream:
            kwargs["stream"] = True
            # streaming with stream_options for usage stats (newer OpenAI feature)
            kwargs.setdefault("stream_options", {"include_usage": True})

        # Optional parameters from extra_config or request
        if request.tools:
            kwargs["tools"] = request.tools

        if self._response_format:
            kwargs["response_format"] = self._response_format

        if self._stop:
            kwargs["stop"] = self._stop

        if self._top_p is not None:
            kwargs["top_p"] = self._top_p

        if self._frequency_penalty is not None:
            kwargs["frequency_penalty"] = self._frequency_penalty

        if self._presence_penalty is not None:
            kwargs["presence_penalty"] = self._presence_penalty

        if self._extra_body:
            kwargs["extra_body"] = self._extra_body

        return kwargs

    # ------------------------------------------------------------------
    # Responses kwargs builder
    # ------------------------------------------------------------------

    def _build_responses_kwargs(
        self,
        request: LLMRequest,
        instructions: Optional[str],
        tools: Optional[List[Dict]],
        stream: bool,
    ) -> Dict[str, Any]:
        """Build kwargs dict for client.responses.create()."""
        kwargs: Dict[str, Any] = {
            "model": self.model_id,
        }

        # input: combine system prompt + messages into single input
        input_parts: List[Dict[str, Any]] = []
        if request.system_prompt:
            input_parts.append({"role": "system", "content": request.system_prompt})
        input_parts.extend(request.messages)
        kwargs["input"] = input_parts

        # temperature
        temperature = request.temperature if request.temperature is not None else self.config.temperature
        kwargs["temperature"] = temperature

        # instructions (resolutions API equivalent of system prompt)
        if instructions:
            kwargs["instructions"] = instructions

        # tools
        all_tools = request.tools or []
        if tools:
            all_tools = all_tools + tools
        if all_tools:
            kwargs["tools"] = all_tools

        # max_output_tokens
        max_tok = request.max_tokens or self.config.max_tokens
        if max_tok:
            kwargs["max_output_tokens"] = max_tok

        # streaming
        if stream:
            kwargs["stream"] = True

        return kwargs

    # ------------------------------------------------------------------
    # Response content extractors
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(resp: Any) -> str:
        """Extract text from a chat.completions response."""
        try:
            return resp.choices[0].message.content or ""
        except (AttributeError, IndexError):
            return ""

    @staticmethod
    def _extract_delta(chunk: Any) -> Optional[str]:
        """Extract delta text from a streaming chat.completions chunk."""
        try:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                return chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            pass
        return None

    @staticmethod
    def _extract_response_text(resp: Any) -> str:
        """Extract text from a responses.create() response."""
        try:
            for item in resp.output:
                if getattr(item, "type", None) == "message":
                    for block in getattr(item, "content", []):
                        if getattr(block, "type", None) == "output_text":
                            return getattr(block, "text", "") or ""
        except (AttributeError, TypeError):
            pass
        return ""

    # ------------------------------------------------------------------
    # Auto-detect: try responses API, fall back to chat
    # ------------------------------------------------------------------

    async def generate(
        self,
        request: LLMRequest,
        prefer_responses: Optional[bool] = None,
    ) -> str:
        """Smart generation: auto-detect whether to use /v1/responses or /v1/chat.

        If `prefer_responses` is True (or extra_config.use_responses is True),
        tries /v1/responses first and falls back to /v1/chat/completions on failure.
        Otherwise uses /v1/chat/completions directly.
        """
        use_responses = prefer_responses if prefer_responses is not None else self._use_responses_default

        if use_responses:
            try:
                return await self.responses(request)
            except Exception:
                from loguru import logger
                logger.debug(
                    f"UniversalProvider [{self.config.name}]: "
                    f"/v1/responses failed, falling back to /v1/chat/completions"
                )

        return await self.chat(request)

    # ------------------------------------------------------------------
    # Health check override
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        """Health check: try a minimal chat completion."""
        try:
            await self.chat(LLMRequest(
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            ))
            return True
        except Exception:
            return False


# ------------------------------------------------------------------
# Backward compatibility alias
# ------------------------------------------------------------------
OpenAICompatProvider = UniversalProvider
