"""
LLM Router — 统一模型调度器

职责:
1. 多厂商/多Key管理
2. 按场景标签智能路由
3. 失败自动降级切换
4. 加权负载均衡
5. 健康监控
"""
import random
import time
from collections import defaultdict
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from loguru import logger

from .base import BaseLLMProvider, LLMRequest, ModelConfig
from ..config import config as app_config

# 惰性导入 provider 类
AnthropicProvider = None
OpenAIProvider = None
UniversalProvider = None

def _ensure_providers():
    global AnthropicProvider, OpenAIProvider, UniversalProvider
    if AnthropicProvider is None:
        try:
            from .anthropic_provider import AnthropicProvider as AP
            AnthropicProvider = AP
        except ImportError:
            pass
    if OpenAIProvider is None:
        try:
            from .openai_provider import OpenAIProvider as OP
            OpenAIProvider = OP
        except ImportError:
            pass
    if UniversalProvider is None:
        try:
            from .openai_compat import UniversalProvider as UP
            UniversalProvider = UP
        except ImportError:
            pass


@dataclass
class ProviderEntry:
    """带权重的 Provider 条目"""
    provider: BaseLLMProvider
    config: ModelConfig
    failures: int = 0
    last_failure_time: float = 0
    total_calls: int = 0
    total_tokens: int = 0
    avg_latency: float = 0


class LLMRouter:
    """
    统一 LLM 调度器

    使用方式:
        router = LLMRouter()
        router.register_from_app_config()

        reply = await router.generate(
            request=LLMRequest(
                messages=[{"role": "user", "content": "你好"}],
                system_prompt="你是小糖...",
            ),
            scene="default"
        )
    """

    def __init__(self):
        # tag → [ProviderEntry, ...]
        self.providers: Dict[str, List[ProviderEntry]] = defaultdict(list)
        # 所有 provider 的扁平列表 (用于遍历)
        self.all_entries: List[ProviderEntry] = []

        # 降级顺序 (字符串)
        self.fallback_order = ["anthropic", "openai", "openai_compat"]

        # 熔断阈值
        self.circuit_breaker_threshold = 3         # 连续失败 N 次后熔断
        self.circuit_breaker_cooldown = 60          # 熔断冷却时间 (秒)

    # ── 注册 ──────────────────────────────────────

    def register(self, config: ModelConfig) -> Optional[BaseLLMProvider]:
        """注册一个模型配置 (支持任意 provider 字符串: anthropic, openai, openai_compat, custom, ...)"""
        if not config.enabled:
            return None

        # 跳过没有 API Key 的模型 (需用户在 GUI 中配置)
        if not config.api_key or config.api_key.startswith("${"):
            logger.info(f"LLM Router: skipping [{config.name}] — no API key configured (set in GUI)")
            return None

        _ensure_providers()

        provider_type = (config.provider or "").lower()

        try:
            if provider_type == "anthropic":
                provider = AnthropicProvider(config)
            elif provider_type == "openai":
                provider = OpenAIProvider(config)
            else:
                # 所有其他类型 (openai_compat, custom, relay, ...) 都用 UniversalProvider
                provider = UniversalProvider(config)
        except ImportError as e:
            logger.warning(f"Cannot create provider [{config.name}]: {e}. SDK not installed?")
            return None
        except Exception as e:
            logger.error(f"Failed to create provider [{config.name}]: {e}")
            return None

        entry = ProviderEntry(provider=provider, config=config)

        for tag in config.tags or ["default"]:
            self.providers[tag].append(entry)

        self.all_entries.append(entry)
        logger.info(f"LLM Router: registered [{config.name}] ({config.provider}/{config.model_id}) tags={config.tags}")

        return provider

    def register_from_app_config(self):
        """从应用配置加载所有模型 (内存中的 models 列表)"""
        self.providers.clear()
        self.all_entries.clear()

        for model_config in app_config.models:
            self.register(model_config)

        # 覆盖降级顺序 (直接使用字符串)
        if app_config.routing.fallback_order:
            self.fallback_order = app_config.routing.fallback_order

        logger.info(f"LLM Router: loaded {len(self.all_entries)} providers, "
                     f"tags={list(self.providers.keys())}")

    async def reload_from_db(self, db_session):
        """从数据库重新加载所有模型配置 (GUI 修改 API Key 后调用)"""
        from ..config import load_models_from_db

        # 从 DB 加载含 API Key 的完整模型列表
        models = await load_models_from_db(db_session)

        # 更新全局配置
        app_config.models = models

        # 重新注册
        self.register_from_app_config()

        logger.info(f"LLM Router: reloaded from DB, {len(self.all_entries)} providers active")
        return self.get_status()

    # ── 路由 ──────────────────────────────────────

    async def generate(self,
                       request: LLMRequest,
                       scene: str = "default") -> str:
        """
        智能路由生成

        scene 映射到标签:
        - "default"    → 日常售前咨询
        - "reasoning"  → 售后投诉分析、回复质检
        - "cheap"      → FAQ匹配、意图分类
        - "fast"       → 订单查询等快速响应
        """
        # 确定目标标签
        tag = request.preferred_tag or scene

        # 获取候选 Provider
        candidates = self._get_candidates(tag)

        if not candidates:
            raise RuntimeError(f"No enabled provider found for tag: {tag}")

        # 上次错误
        last_error = None

        # 尝试候选
        for entry in candidates:
            if self._is_circuit_open(entry):
                continue

            try:
                start = time.time()
                result = await entry.provider.chat(request)
                elapsed = time.time() - start

                # 更新统计
                entry.failures = 0
                entry.total_calls += 1
                entry.avg_latency = (entry.avg_latency * (entry.total_calls - 1) + elapsed) / entry.total_calls

                return result

            except Exception as e:
                last_error = e
                entry.failures += 1
                entry.last_failure_time = time.time()
                logger.warning(f"Provider [{entry.config.name}] failed: {e} (failures: {entry.failures})")
                continue

        # ── 降级：按 fallback_order 尝试所有未尝试的 provider ──
        for fallback_type in self.fallback_order:
            fb_result = await self._try_fallback(fallback_type, request, tag)
            if fb_result:
                return fb_result

        raise RuntimeError(
            f"All LLM providers exhausted. "
            f"Tag={tag}, Scene={scene}, Last error: {last_error}"
        )

    async def generate_with_fallback(self,
                                     request: LLMRequest,
                                     scenes: List[str] = None) -> str:
        """
        带多场景回退的生成
        依次尝试: reasoning → default → cheap
        """
        if scenes is None:
            scenes = ["reasoning", "default", "cheap"]

        last_error = None
        for scene in scenes:
            try:
                return await self.generate(request, scene)
            except RuntimeError as e:
                last_error = e
                logger.warning(f"Scene '{scene}' failed, trying next...")

        raise RuntimeError(f"All scenes exhausted. Last error: {last_error}")

    # ── 内部方法 ──────────────────────────────────

    def _get_candidates(self, tag: str) -> List[ProviderEntry]:
        """获取候选 Provider (按标签)"""
        # 场景标签映射 (从配置)
        scene_tags = app_config.routing.scene_tags
        preferred_tags = scene_tags.get(tag, [tag, "cheap", "default"])

        candidates = []
        seen = set()

        for t in preferred_tags:
            for entry in self.providers.get(t, []):
                key = entry.config.model_id
                if key not in seen:
                    seen.add(key)
                    candidates.append(entry)

        if not candidates:
            # 兜底：所有 enabled 的 provider
            candidates = [e for e in self.all_entries if e.config.enabled]

        # 按权重排序 + 随机扰动
        candidates.sort(
            key=lambda e: (e.config.weight + random.uniform(-10, 10)),
            reverse=True,
        )

        return candidates

    async def _try_fallback(self, ptype: str, request: LLMRequest, exclude_tag: str) -> Optional[str]:
        """尝试降级到指定类型的任意可用 provider"""
        for tag_entries in self.providers.values():
            for entry in tag_entries:
                if entry.provider.provider_type != ptype:
                    continue
                if not entry.config.enabled:
                    continue
                if self._is_circuit_open(entry):
                    continue

                try:
                    return await entry.provider.chat(request)
                except Exception:
                    continue
        return None

    def _is_circuit_open(self, entry: ProviderEntry) -> bool:
        """检查熔断器是否开启"""
        if entry.failures >= self.circuit_breaker_threshold:
            elapsed = time.time() - entry.last_failure_time
            if elapsed < self.circuit_breaker_cooldown:
                return True  # 熔断中
            # 冷却期已过，半开状态
            entry.failures = 0
        return False

    # ── 便捷方法 ──────────────────────────────────

    async def classify(self, text: str, labels: List[str], system: str = None) -> str:
        """意图分类 (使用 cheap 模型)"""
        labels_str = ", ".join(labels)
        prompt = f"将以下文本分类为: {labels_str}。只输出一个标签，不要解释。\n\n文本: {text}"
        msgs = [{"role": "user", "content": prompt}]
        req = LLMRequest(messages=msgs, max_tokens=50, temperature=0.1, preferred_tag="cheap")
        return (await self.generate(req, "cheap")).strip()

    async def summarize(self, text: str, max_length: int = 200) -> str:
        """文本摘要 (使用 cheap 模型)"""
        prompt = f"用不超过{max_length}字总结以下内容:\n\n{text}"
        msgs = [{"role": "user", "content": prompt}]
        req = LLMRequest(messages=msgs, max_tokens=max_length * 2, temperature=0.3, preferred_tag="cheap")
        return (await self.generate(req, "cheap")).strip()

    def get_status(self) -> Dict[str, Any]:
        """获取所有 Provider 状态"""
        status = {}
        for entry in self.all_entries:
            status[entry.config.name] = {
                "provider": entry.config.provider,
                "model": entry.config.model_id,
                "enabled": entry.config.enabled,
                "healthy": entry.failures < self.circuit_breaker_threshold,
                "failures": entry.failures,
                "total_calls": entry.total_calls,
                "avg_latency": round(entry.avg_latency, 3),
            }
        return status


# 全局单例
router = LLMRouter()
