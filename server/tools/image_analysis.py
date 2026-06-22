"""
ImageAnalysisTool - Analyze customer-uploaded images
Features: quality inspection, fit assessment, color accuracy check, OCR text extraction

Uses multimodal LLM (Anthropic Vision / GPT-4V) via the LLM router for visual analysis.
Falls back to text-only description if no multimodal model is available.
"""
import base64
import os
import re
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import urlparse

import httpx
from loguru import logger

from .base import BaseTool, ToolResult
from ..llm.base import LLMRequest
from ..llm.router import router as llm_router

# Attempt to use PIL for local file handling; optional dependency
try:
    from PIL import Image
    import io as _pil_io

    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ── Well-known multimodal-capable providers / model prefixes ──
MULTIMODAL_PROVIDERS = {"anthropic", "openai"}
MULTIMODAL_MODEL_PREFIXES = (
    "claude",       # Anthropic Claude 3+
    "gpt-4o",       # OpenAI GPT-4o
    "gpt-4-turbo",  # GPT-4V
    "gpt-4",        # GPT-4 (some)
    "gemini",       # Google Gemini
    "qwen-vl",      # Qwen Vision
    "glm-4v",       # ChatGLM Vision
    "llava",        # LLaVA
    "pixtral",      # Mistral Pixtral
    "deepseek-vl",  # DeepSeek VL
)


class ImageAnalysisTool(BaseTool):
    """Analyze customer-uploaded images using multimodal LLM.

    Sub-actions:
    - analyze_quality     : check for visible defects (scratches, stains, tears, etc.)
    - analyze_fit         : assess garment/product fit from customer photo
    - analyze_color_match : compare color accuracy vs product listing photos
    - extract_text        : OCR text from screenshots (orders, chat logs, etc.)
    """

    name: str = "image_analysis"
    description: str = (
        "分析客户上传的图片: 检测质量问题(瑕疵、破损)、评估上身效果、"
        "检查色差、或从截图/订单照片中提取文字(OCR)。"
        "action 可选: analyze_quality, analyze_fit, analyze_color_match, extract_text"
    )
    category: str = "media"
    parameters: dict = {
        "action": {
            "type": "string",
            "description": "分析类型: analyze_quality | analyze_fit | analyze_color_match | extract_text",
            "enum": ["analyze_quality", "analyze_fit", "analyze_color_match", "extract_text"],
        },
        "image_url": {
            "type": "string",
            "description": "图片URL或本地文件路径 (支持 http/https URL 或绝对/相对文件路径)",
        },
        "context": {
            "type": "string",
            "description": "额外上下文 (如客户描述的问题、订单号等)，仅 analyze_quality 使用",
        },
        "product_info": {
            "type": "string",
            "description": "产品信息 (如尺码、款式、版型描述)，仅 analyze_fit 使用",
        },
        "product_id": {
            "type": "string",
            "description": "产品ID或名称，用于在知识库中查找产品原图对比，仅 analyze_color_match 使用",
        },
    }

    def __init__(self, llm_router=None):
        super().__init__()
        self.router = llm_router or llm_router  # use global singleton if none passed

    # ── 主入口 ──────────────────────────────────────

    async def execute(self, **kwargs) -> ToolResult:
        """Router for sub-actions."""
        action = kwargs.get("action", "analyze_quality")
        image_url = kwargs.get("image_url", "")

        if not image_url:
            return ToolResult(success=False, error="缺少参数: image_url")

        if action == "analyze_quality":
            context = kwargs.get("context")
            return await self.analyze_quality(image_url, context)
        elif action == "analyze_fit":
            product_info = kwargs.get("product_info")
            return await self.analyze_fit(image_url, product_info)
        elif action == "analyze_color_match":
            product_id = kwargs.get("product_id")
            return await self.analyze_color_match(image_url, product_id)
        elif action == "extract_text":
            return await self.extract_text(image_url)
        else:
            return ToolResult(success=False, error=f"未知 action: {action}")

    # ── 公开分析方法 ────────────────────────────────

    async def analyze_quality(
        self,
        image_url: str,
        context: Optional[str] = None,
    ) -> ToolResult:
        """Check customer photo for visible defects.

        Typical triggers: customer sends a photo of a defect, "这里有个瑕疵", etc.
        """
        context_str = f"\n客户补充描述: {context}" if context else ""

        system = (
            "你是一名资深的电商服装质检专家，拥有十年验货经验。"
            "仔细查看客户上传的图片，找出所有可见的质量问题。"
            "只分析图片中确实能看到的问题，不要猜测。"
        )

        user = (
            f"请仔细检查这张图片中的可见质量问题:\n"
            f"- 线头、开线、脱线\n"
            f"- 破洞、撕裂、勾丝\n"
            f"- 污渍、色斑、褪色\n"
            f"- 印花脱落、掉色\n"
            f"- 纽扣/拉链损坏\n"
            f"- 走线歪斜、不对称\n"
            f"- 面料起球、刮痕\n"
            f"- 尺寸标注与实物不符(可度量时)\n"
            f"- 其他明显瑕疵\n\n"
            f"请按以下 JSON 格式返回结果 (只返回 JSON，不要其他文字):\n"
            f'{{"has_defects": true/false,'
            f'"defects": [{{"type": "缺陷类型", "description": "具体描述", "severity": "轻微/中等/严重", "location": "位置"}}],'
            f'"overall_assessment": "总体评价(50字以内)",'
            f'"action_suggestion": "建议处理方式(退货/换货/补偿/不处理)"}}'
            f'{context_str}'
        )

        return await self._analyze_image(system, user, image_url)

    async def analyze_fit(
        self,
        image_url: str,
        product_info: Optional[str] = None,
    ) -> ToolResult:
        """Assess garment fit from a customer try-on photo.

        Typical triggers: "你看这个穿上合适吗", "会不会太大了"
        """
        product_str = f"\n产品信息: {product_info}" if product_info else ""

        system = (
            "你是一名专业的服装穿搭与尺码顾问。根据客户的上身照片和产品信息，"
            "评估服装的合身程度。注意观察肩宽、袖长、衣长、胸围、腰围等关键部位的穿着效果。"
        )

        user = (
            f"请根据图片评估这件服装的上身效果/合身度:\n"
            f"- 肩部是否合适 (肩线位置)\n"
            f"- 袖长是否合理\n"
            f"- 衣长/裤长是否合适\n"
            f"- 胸围/腰围是否合身 (过紧/过松)\n"
            f"- 整体版型效果如何\n"
            f"- 有无明显不合身的迹象 (皱褶过多、紧绷拉扯、垂坠不自然)\n\n"
            f"请按以下 JSON 格式返回结果 (只返回 JSON):\n"
            f'{{"fit_assessment": "合身/偏大/偏小/无法判断",'
            f'"confidence": 0.0-1.0,'
            f'"details": [{{"area": "部位", "observation": "观察", "suggestion": "建议尺码调整"}}],'
            f'"overall_comment": "总体评价(50字以内)",'
            f'"recommendation": "建议保留/建议换尺码/建议退货"}}'
            f'{product_str}'
        )

        return await self._analyze_image(system, user, image_url)

    async def analyze_color_match(
        self,
        image_url: str,
        product_id: Optional[str] = None,
    ) -> ToolResult:
        """Check color accuracy of a customer photo vs product listing.

        Typical triggers: "你看这个色差大吗", "颜色和图片不一样"
        """
        product_str = f"\n对比产品: {product_id}" if product_id else ""

        system = (
            "你是一名专业的色彩分析师，精于判断实物与商品图的颜色偏差。"
            "请仔细分析客户照片中的颜色。"
            "注意区分光线/拍摄环境造成的自然偏差与真正的颜色不符。"
        )

        user = (
            f"请分析这张客户照片中产品的颜色:\n"
            f"- 描述图片中看到的实际颜色\n"
            f"- 考虑光线影响 (自然光/室内光/闪光灯)\n"
            f"- 判断可能存在的色差类型 (偏黄/偏蓝/偏红/偏暗/偏亮/饱和度差异)\n"
            f"- 评估色差严重程度\n\n"
            f"请按以下 JSON 格式返回结果 (只返回 JSON):\n"
            f'{{"observed_color": "观察到的颜色描述",'
            f'"lighting_condition": "光线条件推测",'
            f'"color_shift": {{"type": "偏黄/偏蓝/偏红/偏暗/偏亮/偏灰/无", "severity": "轻微/明显/严重"}},'
            f'"is_acceptable": true/false,'
            f'"explanation": "详细解释(50字以内)"}}'
            f'{product_str}'
        )

        return await self._analyze_image(system, user, image_url)

    async def extract_text(self, image_url: str) -> ToolResult:
        """OCR: extract text from order screenshots, chat logs, etc.

        Typical triggers: customer sends a screenshot of an order, receipt, or chat.
        """
        system = (
            "你是一款精准的 OCR 文字提取工具。从图片中提取所有可见的中文和英文文本。"
            "保留原始格式(换行、段落)。不要总结或解释，只输出提取的文本。"
            "如果图片中有表格或结构化信息(如订单号、金额、日期)，请按字段整理。"
        )

        user = (
            "请提取这张图片中的所有文字内容。\n"
            "如果是订单截图，请特别标注出:\n"
            "- 订单号\n"
            "- 购买商品\n"
            "- 金额\n"
            "- 日期\n"
            "- 收货地址(部分脱敏)\n"
            "- 物流单号\n\n"
            "直接输出提取到的文本，不要添加其他说明。"
        )

        return await self._analyze_image(system, user, image_url, json_expected=False)

    # ── 核心: 图片分析调用 ──────────────────────────

    async def _analyze_image(
        self,
        system_prompt: str,
        user_prompt: str,
        image_url: str,
        json_expected: bool = True,
    ) -> ToolResult:
        """Core method: fetch image, build multimodal request, call LLM router."""
        # 1. Fetch image data
        try:
            image_data, mime_type = await self._fetch_image(image_url)
        except Exception as e:
            logger.error(f"Failed to fetch image: {e}")
            return ToolResult(success=False, error=f"无法获取图片: {e}")

        # 2. Check whether a multimodal-capable provider exists
        provider_type, model_id = self._detect_multimodal_provider()
        if provider_type is None:
            # Fallback to text-only analysis
            fallback = await self._fallback_text_only_analysis(system_prompt, user_prompt)
            if fallback:
                return ToolResult(
                    success=True,
                    data={"analysis": fallback},
                    metadata={"method": "text_fallback", "warning": "未配置多模态模型"},
                )
            return ToolResult(
                success=False,
                error=(
                    "当前未配置多模态模型 (需要 Claude 3+/GPT-4V/GPT-4o/Gemini 等支持图片分析的模型)。"
                    "请在 LLM 设置中添加一个支持视觉的模型。"
                ),
            )

        # 3. Build multimodal messages
        messages = self._build_multimodal_messages(
            provider_type, user_prompt, image_data, mime_type
        )

        # 4. Call LLM router
        request = LLMRequest(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.3,
            max_tokens=2048,
            preferred_tag="reasoning",
        )

        try:
            raw = await self.router.generate(request, "reasoning")
        except Exception as e:
            logger.error(f"Multimodal LLM call failed: {e}")
            # Fallback: try text-only description
            fallback = await self._fallback_text_only_analysis(system_prompt, user_prompt)
            if fallback:
                return ToolResult(
                    success=True,
                    data={"analysis": fallback, "method": "text_fallback"},
                    metadata={"provider": provider_type, "model": model_id, "warning": str(e)},
                )
            return ToolResult(success=False, error=f"LLM 调用失败: {e}")

        # 5. Parse response
        if json_expected:
            parsed = self._parse_json_response(raw)
            return ToolResult(
                success=True,
                data=parsed if isinstance(parsed, dict) else {"analysis": raw},
                metadata={"provider": provider_type, "model": model_id},
            )
        else:
            return ToolResult(
                success=True,
                data={"text": raw.strip()},
                metadata={"provider": provider_type, "model": model_id},
            )

    # ── 图片获取 ─────────────────────────────────────

    async def _fetch_image(self, image_url: str) -> Tuple[str, str]:
        """Fetch image from URL or local path, return (base64_encoded, mime_type)."""
        is_url = bool(urlparse(image_url).scheme in ("http", "https"))

        if is_url:
            async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
                resp = await client.get(image_url)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/jpeg")
                mime_type = self._normalize_mime(content_type)
                raw_bytes = resp.content
        else:
            # Local file path
            path = Path(image_url)
            if not path.is_absolute():
                # Relative to project root
                from ..config import PROJECT_ROOT
                path = PROJECT_ROOT / image_url
            if not path.exists():
                raise FileNotFoundError(f"Local image not found: {path}")

            raw_bytes = path.read_bytes()
            ext = path.suffix.lower()
            mime_map = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
                ".bmp": "image/bmp",
                ".tiff": "image/tiff",
            }
            mime_type = mime_map.get(ext, "image/jpeg")

        # Optionally resize large images with PIL
        if HAS_PIL:
            try:
                img = Image.open(_pil_io.BytesIO(raw_bytes))
                w, h = img.size
                max_dim = 2048
                if max(w, h) > max_dim:
                    ratio = max_dim / max(w, h)
                    img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
                buf = _pil_io.BytesIO()
                fmt = "JPEG" if mime_type in ("image/jpeg", "image/webp", "image/bmp") else "PNG"
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGB")
                img.save(buf, format=fmt, optimize=True)
                raw_bytes = buf.getvalue()
                mime_type = "image/jpeg" if fmt == "JPEG" else "image/png"
            except Exception as e:
                logger.debug(f"PIL resize skipped: {e}")

        return base64.b64encode(raw_bytes).decode("utf-8"), mime_type

    @staticmethod
    def _normalize_mime(content_type: str) -> str:
        """Normalize content-type header to a standard MIME type."""
        content_type = content_type.lower().strip()
        if "jpeg" in content_type or "jpg" in content_type:
            return "image/jpeg"
        if "png" in content_type:
            return "image/png"
        if "gif" in content_type:
            return "image/gif"
        if "webp" in content_type:
            return "image/webp"
        return "image/jpeg"  # default

    # ── 多模态消息构建 ──────────────────────────────

    def _build_multimodal_messages(
        self,
        provider_type: str,
        text_prompt: str,
        image_base64: str,
        mime_type: str,
    ) -> List[Dict[str, Any]]:
        """Build multimodal messages in the format expected by the target provider."""
        data_url = f"data:{mime_type};base64,{image_base64}"

        if provider_type == "anthropic":
            return [{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_base64,
                        },
                    },
                    {"type": "text", "text": text_prompt},
                ],
            }]
        else:
            # OpenAI / OpenAI-compatible format (also works for many compatible APIs)
            return [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": data_url, "detail": "auto"},
                    },
                    {"type": "text", "text": text_prompt},
                ],
            }]

    # ── Provider 检测 ────────────────────────────────

    def _detect_multimodal_provider(self) -> Tuple[Optional[str], Optional[str]]:
        """Check router registry for a multimodal-capable provider.

        Returns (provider_type, model_id) or (None, None).
        """
        for entry in self.router.all_entries:
            cfg = entry.config
            if not cfg.enabled:
                continue

            ptype = (cfg.provider or "").lower()
            model = (cfg.model_id or "").lower()

            # Known multimodal providers
            if ptype in MULTIMODAL_PROVIDERS:
                return ptype, cfg.model_id

            # Check for multimodal model prefixes in other providers
            if any(model.startswith(prefix.lower()) for prefix in MULTIMODAL_MODEL_PREFIXES):
                return ptype, cfg.model_id

        return None, None

    # ── 响应解析 ─────────────────────────────────────

    @staticmethod
    def _parse_json_response(raw: str) -> Optional[dict]:
        """Extract JSON from LLM response (robust against markdown fences)."""
        if not raw:
            return None

        # Try direct parse
        try:
            return json.loads(raw.strip())
        except json.JSONDecodeError:
            pass

        # Try to extract from markdown code block
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try to find the first { ... } block
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start:end + 1])
            except json.JSONDecodeError:
                pass

        return None

    # ── 降级: 无视觉模型时文本分析 ──────────────────

    async def _fallback_text_only_analysis(
        self,
        system_prompt: str,
        user_prompt: str,
    ) -> Optional[str]:
        """Fallback: use text-only LLM when no multimodal model is available.

        Returns a helpful message explaining the limitation and guiding next steps.
        """
        try:
            fallback_prompt = (
                f"{user_prompt}\n\n"
                "[注意: 当前未接入多模态模型，无法查看图片。"
                "请根据以上提示词告知用户: 目前暂时无法自动分析图片，"
                "建议用户详细描述图片中的问题(位置、大小、颜色等)，"
                "或引导用户等待人工客服查看图片后再处理。]"
            )
            request = LLMRequest(
                messages=[{"role": "user", "content": fallback_prompt}],
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=512,
                preferred_tag="cheap",
            )
            return await self.router.generate(request, "cheap")
        except Exception as e:
            logger.warning(f"Fallback text analysis also failed: {e}")
            return None


# ── 便捷工厂函数 ────────────────────────────────────


def create_tool(llm_router=None) -> ImageAnalysisTool:
    """Create a configured ImageAnalysisTool instance.

    Args:
        llm_router: LLMRouter instance. Uses global singleton if not provided.
    """
    return ImageAnalysisTool(llm_router=llm_router)


# ── 模块级便捷异步函数 (供 agent 直接调用，不通过 registry) ──

_tool_instance: Optional[ImageAnalysisTool] = None


def _get_tool() -> ImageAnalysisTool:
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = ImageAnalysisTool()
    return _tool_instance


async def analyze_quality(
    image_url: str,
    context: Optional[str] = None,
) -> ToolResult:
    """Check customer photo for visible defects. (Convenience function)

    Use case: Customer sends photo of a defect → agent calls analyze_quality.
    """
    return await _get_tool().analyze_quality(image_url, context)


async def analyze_fit(
    image_url: str,
    product_info: Optional[str] = None,
) -> ToolResult:
    """Assess garment fit from a customer try-on photo. (Convenience function)

    Use case: Customer asks "你看这个穿上合适吗" → agent calls analyze_fit.
    """
    return await _get_tool().analyze_fit(image_url, product_info)


async def analyze_color_match(
    image_url: str,
    product_id: Optional[str] = None,
) -> ToolResult:
    """Check color accuracy of a customer photo vs product listing. (Convenience function)

    Use case: Customer asks "你看这个色差大吗" → agent calls analyze_color_match.
    """
    return await _get_tool().analyze_color_match(image_url, product_id)


async def extract_text(image_url: str) -> ToolResult:
    """OCR extract text from screenshots or order photos. (Convenience function)

    Use case: Customer sends order screenshot → agent calls extract_text.
    """
    return await _get_tool().extract_text(image_url)
