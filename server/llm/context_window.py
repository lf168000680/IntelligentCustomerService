"""
Context Window Manager — 模型上下文窗口自动检测与管理

职责:
1. 维护已知模型的上下文窗口大小数据库
2. 支持从 providers.yaml 读取自定义 context_window
3. 自动匹配模型 ID (模糊匹配)
4. 提供 token 预算计算 (80% 阈值等)
"""
import re
from typing import Optional, Dict, Tuple

from loguru import logger


# ═══════════════════════════════════════════════════════════════
# 已知模型上下文窗口大小 (tokens) — 持续更新
# ═══════════════════════════════════════════════════════════════
KNOWN_CONTEXT_WINDOWS: Dict[str, int] = {
    # ── Anthropic Claude ──
    "claude-sonnet-4-6": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4-8": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-opus-4": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-haiku-4": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-haiku": 200_000,
    "claude-2.1": 200_000,
    "claude-2.0": 100_000,

    # ── OpenAI ──
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.5": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-1106": 128_000,
    "gpt-4-0125": 128_000,
    "gpt-4": 8_192,
    "gpt-4-32k": 32_768,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5-turbo-16k": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "gpt-5": 128_000,

    # ── DeepSeek ──
    "deepseek-chat": 65_536,
    "deepseek-v3": 65_536,
    "deepseek-reasoner": 65_536,
    "deepseek-r1": 65_536,

    # ── 豆包 (Doubao / 火山引擎 Ark) ──
    "doubao-lite-32k": 32_768,
    "doubao-lite-4k": 4_096,
    "doubao-pro-32k": 32_768,
    "doubao-pro-128k": 131_072,
    "doubao-pro": 131_072,
    "doubao": 32_768,

    # ── 通义千问 (Qwen) ──
    "qwen-turbo": 131_072,
    "qwen-turbo-latest": 1_000_000,
    "qwen-plus": 131_072,
    "qwen-plus-latest": 131_072,
    "qwen-max": 32_768,
    "qwen-max-long": 1_000_000,
    "qwen-long": 10_000_000,  # 理论 10M
    "qwen": 131_072,

    # ── 智谱 GLM ──
    "glm-4-flash": 128_000,
    "glm-4": 128_000,
    "glm-4-plus": 128_000,
    "glm-4-air": 128_000,
    "glm-4-long": 1_000_000,
    "glm-3-turbo": 128_000,

    # ── Groq ──
    "llama-3.1-70b-versatile": 128_000,
    "llama-3.1-8b-instant": 128_000,
    "llama-3.3-70b": 128_000,
    "llama-3.2-90b": 128_000,

    # ── OpenRouter 常见模型 ──
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "anthropic/claude-sonnet-4-6": 200_000,
    "anthropic/claude-opus-4-8": 200_000,
    "anthropic/claude-haiku-4-5": 200_000,
    "google/gemini-pro": 32_768,
    "google/gemini-flash": 1_000_000,
    "meta-llama/llama-3.1-70b": 128_000,
    "meta-llama/llama-3.1-8b": 128_000,
    "mistral/mistral-large": 128_000,
    "mistral/mistral-small": 32_000,

    # ── 本地模型 ──
    "llama-3.1-8b": 128_000,
    "qwen2.5-7b": 128_000,
    "qwen2.5-14b": 128_000,
    "qwen2.5-72b": 128_000,

    # ── Mistral ──
    "mistral-large": 128_000,
    "mistral-small": 32_000,
    "mistral-medium": 32_000,

    # ── Google Gemini (via OpenAI compat) ──
    "gemini-pro": 32_768,
    "gemini-flash": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-2.0-flash": 1_000_000,
}

# 默认值 — 当模型不在已知列表中时使用
DEFAULT_CONTEXT_WINDOW = 8_192

# 安全上限 — 超过此值视为虚标
MAX_SAFE_WINDOW = 2_000_000


def get_context_window(model_id: str, custom_window: Optional[int] = None) -> int:
    """
    获取模型的上下文窗口大小。

    优先级:
    1. custom_window (来自 providers.yaml 显式配置)
    2. KNOWN_CONTEXT_WINDOWS 精确匹配
    3. KNOWN_CONTEXT_WINDOWS 前缀/子串匹配
    4. 根据模型名推断 (32k/128k/200k 等后缀)
    5. DEFAULT_CONTEXT_WINDOW

    Args:
        model_id: 模型标识符，如 "claude-sonnet-4-6", "gpt-4o"
        custom_window: 用户在 providers.yaml 中显式配置的上下文窗口

    Returns:
        上下文窗口大小 (tokens)
    """
    if custom_window and custom_window > 0:
        return min(custom_window, MAX_SAFE_WINDOW)

    if not model_id:
        return DEFAULT_CONTEXT_WINDOW

    model_lower = model_id.lower().strip()

    # 1. 精确匹配
    if model_lower in KNOWN_CONTEXT_WINDOWS:
        return KNOWN_CONTEXT_WINDOWS[model_lower]

    # 2. 前缀匹配 (处理带日期后缀的模型: claude-sonnet-4-6-20250601)
    for known_id, window in sorted(KNOWN_CONTEXT_WINDOWS.items(),
                                    key=lambda x: -len(x[0])):
        if model_lower.startswith(known_id) or known_id in model_lower:
            logger.debug(f"Context window fuzzy match: '{model_id}' → '{known_id}' = {window:,}")
            return window

    # 3. 从模型名推断 (匹配类似 "xxx-32k", "xxx-128k", "xxx-200k" 等)
    inferred = _infer_from_name(model_lower)
    if inferred:
        logger.debug(f"Context window inferred from name: '{model_id}' → {inferred:,}")
        return inferred

    # 4. 兜底
    logger.warning(
        f"Unknown model '{model_id}', using default context window: {DEFAULT_CONTEXT_WINDOW:,} "
        f"(set context_window in providers.yaml to override)"
    )
    return DEFAULT_CONTEXT_WINDOW


def _infer_from_name(model_lower: str) -> Optional[int]:
    """从模型名推断上下文窗口。"""
    # 匹配 "xxx-Nk" 或 "xxx-NK" 模式
    match = re.search(r'[-_](\d+)k\b', model_lower)
    if match:
        return int(match.group(1)) * 1024

    # 匹配 "xxx-1m", "xxx-2m" 等
    match = re.search(r'[-_](\d+)m\b', model_lower)
    if match:
        return int(match.group(1)) * 1_000_000

    # 匹配 "xxx-128000" 等直接数字
    match = re.search(r'[-_](\d{4,7})\b', model_lower)
    if match:
        val = int(match.group(1))
        if 4000 <= val <= 10_000_000:
            return val

    return None


class ContextBudget:
    """
    上下文预算管理器。

    计算当前 token 用量是否超过阈值，决定是否需要压缩。
    """

    def __init__(self,
                 context_window: int,
                 compress_threshold: float = 0.80,
                 severe_threshold: float = 0.95,
                 safe_margin: int = 512):
        """
        Args:
            context_window: 模型总上下文窗口 (tokens)
            compress_threshold: 触发压缩的阈值 (默认 80%)
            severe_threshold: 严重超限阈值 (默认 95%)，触发激进压缩
            safe_margin: 安全边距，为响应留出空间 (tokens)
        """
        self.context_window = context_window
        self.compress_threshold = compress_threshold
        self.severe_threshold = severe_threshold
        self.safe_margin = safe_margin

        # 有效工作窗口 = 总窗口 - 安全边距
        self.effective_window = context_window - safe_margin

        # 各阈值绝对 token 数
        self.compress_at = int(self.effective_window * compress_threshold)
        self.severe_at = int(self.effective_window * severe_threshold)

    @property
    def max_output_tokens(self) -> int:
        """建议的 max_tokens (为响应预留空间)。"""
        return max(256, self.safe_margin)

    def check(self, estimated_tokens: int) -> Tuple[str, bool, float]:
        """
        检查 token 用量状态。

        Returns:
            (status, needs_compression, usage_ratio)
            status: "ok" | "warn" | "compress" | "severe"
        """
        ratio = estimated_tokens / self.effective_window if self.effective_window > 0 else 0

        if estimated_tokens >= self.severe_at:
            return ("severe", True, ratio)
        elif estimated_tokens >= self.compress_at:
            return ("compress", True, ratio)
        elif estimated_tokens >= self.compress_at * 0.75:
            return ("warn", False, ratio)
        else:
            return ("ok", False, ratio)

    def target_after_compression(self, current_tokens: int) -> int:
        """压缩后目标 token 数 (一般是阈值的 60%，留出增长空间)。"""
        return int(self.compress_at * 0.6)

    def __repr__(self) -> str:
        return (f"ContextBudget(window={self.context_window:,}, "
                f"compress@>{self.compress_at:,}, severe@>{self.severe_at:,})")


# ═══════════════════════════════════════════════════════════════
# 全局缓存 — 按 model_id 缓存 ContextBudget
# ═══════════════════════════════════════════════════════════════
_budget_cache: Dict[str, ContextBudget] = {}


def get_budget(model_id: str,
               custom_window: Optional[int] = None,
               threshold: float = 0.80,
               safe_margin: int = 512) -> ContextBudget:
    """获取模型的上下文预算管理器 (带缓存)。"""
    cache_key = f"{model_id}:{custom_window}:{threshold}:{safe_margin}"
    if cache_key not in _budget_cache:
        window = get_context_window(model_id, custom_window)
        _budget_cache[cache_key] = ContextBudget(
            context_window=window,
            compress_threshold=threshold,
            safe_margin=safe_margin,
        )
    return _budget_cache[cache_key]


def clear_budget_cache():
    """清除预算缓存 (模型配置变更后调用)。"""
    _budget_cache.clear()
