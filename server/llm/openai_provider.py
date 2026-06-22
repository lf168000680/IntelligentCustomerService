"""
OpenAI Responses API — 原生实现
同时兼容 Chat Completions API 作为 fallback
"""
from typing import AsyncIterator, List, Dict

from .base import BaseLLMProvider, LLMRequest, ModelConfig


class OpenAIProvider(BaseLLMProvider):
    """OpenAI API (gpt-4o, gpt-4o-mini, etc.)"""

    provider_type = "openai"

    def __init__(self, config: ModelConfig):
        super().__init__(config)
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            max_retries=3,
        )

    async def chat(self, request: LLMRequest) -> str:
        """使用 Responses API (新)"""
        messages = self._build_input(request)

        try:
            resp = await self.client.responses.create(
                model=self.model_id,
                input=messages,
                max_output_tokens=request.max_tokens or self.config.max_tokens,
                temperature=request.temperature if request.temperature is not None else self.config.temperature,
            )
            return resp.output_text
        except Exception:
            # Fallback 到 Chat Completions API
            return await self._chat_completions(request, messages)

    async def stream_chat(self, request: LLMRequest) -> AsyncIterator[str]:
        messages = self._build_input(request)

        try:
            async with self.client.responses.stream(
                model=self.model_id,
                input=messages,
                max_output_tokens=request.max_tokens or self.config.max_tokens,
                temperature=request.temperature if request.temperature is not None else self.config.temperature,
            ) as stream:
                async for event in stream:
                    if hasattr(event, "delta") and event.delta:
                        yield event.delta
        except Exception:
            # Fallback 到 Chat Completions stream
            async for chunk in self._chat_completions_stream(request, messages):
                yield chunk

    async def _chat_completions(self, request: LLMRequest, messages: List[Dict]) -> str:
        """Chat Completions API 降级"""
        resp = await self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_tokens=request.max_tokens or self.config.max_tokens,
            temperature=request.temperature if request.temperature is not None else self.config.temperature,
        )
        return resp.choices[0].message.content or ""

    async def _chat_completions_stream(self, request: LLMRequest, messages: List[Dict]) -> AsyncIterator[str]:
        """Chat Completions 流式降级"""
        stream = await self.client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_tokens=request.max_tokens or self.config.max_tokens,
            temperature=request.temperature if request.temperature is not None else self.config.temperature,
            stream=True,
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def _build_input(self, request: LLMRequest) -> List[Dict]:
        """构建 OpenAI 格式输入"""
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.extend(request.messages)
        return messages
