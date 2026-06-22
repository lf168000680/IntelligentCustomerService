"""
WebSearchTool — 网络搜索工具 (async, BaseTool compatible)
"""
import hashlib
import time
from typing import Dict, Optional
import httpx
from loguru import logger
from .base import BaseTool, ToolResult


class WebSearchTool(BaseTool):
    """搜索互联网获取实时信息"""

    name = "web_search"
    description = "搜索互联网获取最新信息。用于产品评价、竞品对比、政策查询、活动信息等"
    category = "data"
    parameters = {
        "query": {"type": "string", "description": "搜索关键词"},
        "num_results": {"type": "integer", "description": "返回结果数(默认5)", "default": 5},
    }

    def __init__(self):
        super().__init__()
        self._cache: Dict[str, tuple] = {}
        self._cache_ttl = 3600
        self._last_request = 0
        self._client = httpx.AsyncClient(timeout=15.0)

    async def execute(self, query: str, num_results: int = 5, **kwargs) -> ToolResult:
        cache_key = hashlib.md5(f"{query}:{num_results}".encode()).hexdigest()
        if cache_key in self._cache:
            data, ts = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return ToolResult.ok(data, source="cache")

        elapsed = time.time() - self._last_request
        if elapsed < 1.0:
            import asyncio
            await asyncio.sleep(1.0 - elapsed)
        self._last_request = time.time()

        try:
            resp = await self._client.get("https://api.duckduckgo.com/", params={
                "q": query, "format": "json", "no_html": 1, "skip_disambig": 1,
            })
            resp.raise_for_status()
            data = resp.json()
            results = []

            if data.get("AbstractText"):
                results.append({"title": data.get("AbstractSource", ""),
                              "snippet": data["AbstractText"],
                              "url": data.get("AbstractURL", "")})

            for topic in data.get("RelatedTopics", [])[:num_results]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append({"title": "", "snippet": topic["Text"],
                                  "url": topic.get("FirstURL", "")})

            seen = set()
            unique = [r for r in results if not (r["snippet"][:80] in seen or seen.add(r["snippet"][:80]))]
            if not unique:
                unique = [{"snippet": f"未找到与'{query}'相关的搜索结果", "url": ""}]

            self._cache[cache_key] = (unique[:num_results], time.time())
            return ToolResult.ok(unique[:num_results], source="duckduckgo", query=query)
        except Exception as e:
            logger.warning(f"WebSearch failed: {e}")
            return ToolResult.ok([{"snippet": f"搜索不可用", "url": ""}], source="fallback")
