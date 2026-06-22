"""
ProductLookupTool — 商品信息查询工具

Agent 使用场景:
- "这件还有M码吗" → check_stock(product_id, sku="尺码:M")
- "这个面料是什么成分" → get_material_info(product_id)
- "什么时候能发货" → get_shipping_info(product_id)
- "帮我查下这款的详情" → get_product(product_id)
- 模糊搜索商品 → search_products(query, top_k=5)
"""
import re
from typing import Optional, List, Dict, Any

from loguru import logger
from sqlalchemy import select, or_
from sqlalchemy.sql import func

from .base import BaseTool, ToolResult


class ProductLookupTool(BaseTool):
    """
    商品信息查询工具

    支持:
    - search_products(query, top_k=5): 按名称/描述模糊搜索商品
    - get_product(product_id): 获取商品完整详情
    - check_stock(product_id, sku?): 查询库存（可按 SKU 精细查询）
    - get_shipping_info(product_id): 运费与配送时效
    - get_size_chart(product_id): 尺码表（服装类）
    - get_material_info(product_id): 面料成分与洗护
    """

    name = "product_lookup"
    description = (
        "查询商品信息：搜索商品、查看详情、检查库存、查询物流/运费、"
        "查看尺码表、查看面料成分与洗护说明。"
    )
    category = "data"
    parameters = {
        "action": {
            "type": "string",
            "enum": [
                "search",
                "get_detail",
                "check_stock",
                "get_shipping",
                "get_size_chart",
                "get_material",
            ],
            "description": "操作类型",
        },
        "query": {
            "type": "string",
            "description": "搜索关键词 (action=search) 或商品ID (其他action)",
        },
        "top_k": {
            "type": "integer",
            "description": "返回商品数量上限，默认 5",
        },
        "sku": {
            "type": "string",
            "description": "SKU 规格描述，如 '颜色:红色,尺码:M'，用于精细化库存查询",
        },
    }

    def __init__(self, db_factory=None):
        """
        Args:
            db_factory: 可选，异步 DB session 工厂。
                       注入后用于查询 Product 表；为 None 时所有方法返回错误。
        """
        self.db_factory = db_factory

    # ── BaseTool 入口 ──────────────────────────────────────

    async def execute(self, **kwargs) -> ToolResult:
        """
        LLM function-calling 统一入口，根据 action 参数分发。
        """
        action = kwargs.get("action", "search")

        if action == "search":
            return await self.search_products(
                query=kwargs.get("query", ""),
                top_k=kwargs.get("top_k", 5),
            )
        elif action == "get_detail":
            return await self.get_product(
                product_id=kwargs.get("query", "")
            )
        elif action == "check_stock":
            return await self.check_stock(
                product_id=kwargs.get("query", ""),
                sku=kwargs.get("sku"),
            )
        elif action == "get_shipping":
            return await self.get_shipping_info(
                product_id=kwargs.get("query", "")
            )
        elif action == "get_size_chart":
            return await self.get_size_chart(
                product_id=kwargs.get("query", "")
            )
        elif action == "get_material":
            return await self.get_material_info(
                product_id=kwargs.get("query", "")
            )
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    # ── 公开方法 ────────────────────────────────────────────

    async def search_products(self, query: str, top_k: int = 5) -> ToolResult:
        """
        按名称、描述或平台商品ID模糊搜索商品。

        Args:
            query: 搜索关键词
            top_k: 返回数量上限，默认 5，最大 20
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not query or not query.strip():
            return ToolResult(success=False, error="搜索关键词不能为空")

        try:
            async with self.db_factory() as db:
                from ..db.models import Product

                pattern = f"%{query.strip()}%"
                limit = max(1, min(top_k or 5, 20))

                stmt = (
                    select(Product)
                    .where(
                        or_(
                            Product.title.ilike(pattern),
                            Product.description.ilike(pattern),
                            Product.platform_product_id.ilike(pattern),
                        )
                    )
                    .order_by(Product.title)
                    .limit(limit)
                )
                result = await db.execute(stmt)
                products = result.scalars().all()

            data = [_product_brief(p) for p in products]
            return ToolResult(
                success=True,
                data=data,
                metadata={"total": len(data), "query": query.strip()},
            )
        except Exception as e:
            logger.error(f"search_products failed: {e}")
            return ToolResult(success=False, error=str(e))

    async def get_product(self, product_id: str) -> ToolResult:
        """
        获取商品完整详情。

        Args:
            product_id: 商品 ID（内部 UUID 或平台商品 ID）
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not product_id or not product_id.strip():
            return ToolResult(success=False, error="product_id 不能为空")

        try:
            product = await self._resolve_product(product_id.strip())
            if not product:
                return ToolResult(
                    success=False, error=f"商品未找到: {product_id}"
                )

            return ToolResult(
                success=True, data=_product_detail(product)
            )
        except Exception as e:
            logger.error(f"get_product failed: {e}")
            return ToolResult(success=False, error=str(e))

    async def check_stock(
        self, product_id: str, sku: Optional[str] = None
    ) -> ToolResult:
        """
        检查商品库存。

        - 不指定 sku：返回总库存 + 各规格库存概览
        - 指定 sku（如 "颜色:红色,尺码:M" 或 "尺码:M"）：
          返回该 SKU 的匹配状态

        Args:
            product_id: 商品 ID
            sku:        可选，SKU 描述字符串
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not product_id or not product_id.strip():
            return ToolResult(success=False, error="product_id 不能为空")

        try:
            product = await self._resolve_product(product_id.strip())
            if not product:
                return ToolResult(
                    success=False, error=f"商品未找到: {product_id}"
                )

            total_stock = product.stock or 0
            specs = product.specs or {}

            # ── 精确 SKU 查询 ──
            if sku:
                matched = _match_sku_stock(specs, sku.strip(), total_stock)
                return ToolResult(
                    success=True,
                    data={
                        "product_id": product.id,
                        "title": product.title,
                        "sku": sku.strip(),
                        "in_stock": matched["in_stock"],
                        "stock_level": matched["level"],
                        "total_stock": total_stock,
                    },
                )

            # ── 总览 ──
            return ToolResult(
                success=True,
                data={
                    "product_id": product.id,
                    "title": product.title,
                    "total_stock": total_stock,
                    "in_stock": total_stock > 0,
                    "stock_level": _stock_level(total_stock),
                    "specs_summary": specs,
                },
            )
        except Exception as e:
            logger.error(f"check_stock failed: {e}")
            return ToolResult(success=False, error=str(e))

    async def get_shipping_info(self, product_id: str) -> ToolResult:
        """
        查询商品物流信息：发货地、快递公司、配送时效、是否包邮。

        Args:
            product_id: 商品 ID
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not product_id or not product_id.strip():
            return ToolResult(success=False, error="product_id 不能为空")

        try:
            product = await self._resolve_product(product_id.strip())
            if not product:
                return ToolResult(
                    success=False, error=f"商品未找到: {product_id}"
                )

            shipping = product.shipping_info or {}

            # 从 description 中补充提取物流相关描述
            extra = _extract_shipping_from_description(
                product.description or ""
            )

            return ToolResult(
                success=True,
                data={
                    "product_id": product.id,
                    "title": product.title,
                    "shipping_info": shipping,
                    "description_notes": extra,
                },
            )
        except Exception as e:
            logger.error(f"get_shipping_info failed: {e}")
            return ToolResult(success=False, error=str(e))

    async def get_size_chart(self, product_id: str) -> ToolResult:
        """
        查询服装类商品的尺码表。

        从 specs['尺码表'] / specs['size_chart'] 中提取结构化尺码数据；
        若不存在，尝试从 description 中提取尺寸相关信息。

        Args:
            product_id: 商品 ID
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not product_id or not product_id.strip():
            return ToolResult(success=False, error="product_id 不能为空")

        try:
            product = await self._resolve_product(product_id.strip())
            if not product:
                return ToolResult(
                    success=False, error=f"商品未找到: {product_id}"
                )

            specs = product.specs or {}

            # 优先取结构化尺码表
            size_chart = (
                specs.get("尺码表")
                or specs.get("size_chart")
            )
            size_options = (
                specs.get("尺码")
                or specs.get("size")
                or []
            )
            if isinstance(size_options, str):
                size_options = [size_options]
            if not isinstance(size_options, list):
                size_options = []

            # 从 description 补充
            desc_hints = _extract_size_from_description(
                product.description or ""
            )

            return ToolResult(
                success=True,
                data={
                    "product_id": product.id,
                    "title": product.title,
                    "size_chart": size_chart,
                    "available_sizes": size_options,
                    "description_hints": desc_hints,
                },
            )
        except Exception as e:
            logger.error(f"get_size_chart failed: {e}")
            return ToolResult(success=False, error=str(e))

    async def get_material_info(self, product_id: str) -> ToolResult:
        """
        查询商品面料成分与洗护说明。

        从 specs['面料'] / specs['材质'] / specs['fabric'] 中提取；
        若不存在，从 description 中提取。

        Args:
            product_id: 商品 ID
        """
        if not self.db_factory:
            return ToolResult(
                success=False, error="DB session factory not available"
            )

        if not product_id or not product_id.strip():
            return ToolResult(success=False, error="product_id 不能为空")

        try:
            product = await self._resolve_product(product_id.strip())
            if not product:
                return ToolResult(
                    success=False, error=f"商品未找到: {product_id}"
                )

            specs = product.specs or {}

            # 结构化字段
            fabric = (
                specs.get("面料")
                or specs.get("材质")
                or specs.get("fabric")
            )
            care = (
                specs.get("洗护")
                or specs.get("洗涤")
                or specs.get("care")
            )

            # 从 description 中补充提取
            desc_fabric, desc_care = _extract_material_from_description(
                product.description or ""
            )

            return ToolResult(
                success=True,
                data={
                    "product_id": product.id,
                    "title": product.title,
                    "fabric_composition": fabric or desc_fabric or None,
                    "care_instructions": care or desc_care or None,
                },
            )
        except Exception as e:
            logger.error(f"get_material_info failed: {e}")
            return ToolResult(success=False, error=str(e))

    # ── 内部辅助 ────────────────────────────────────────────

    async def _resolve_product(self, product_id: str):
        """
        根据 ID 查找商品：先按内部 UUID，再按 platform_product_id。
        """
        from ..db.models import Product

        async with self.db_factory() as db:
            # 先尝试 UUID
            stmt = select(Product).where(Product.id == product_id)
            result = await db.execute(stmt)
            product = result.scalar_one_or_none()
            if product:
                return product

            # 再尝试平台商品 ID
            stmt = select(Product).where(
                Product.platform_product_id == product_id
            )
            result = await db.execute(stmt)
            return result.scalars().first()


# ================================================================
# 纯函数辅助 — 格式化 & 文本提取
# ================================================================

def _product_brief(product) -> dict:
    """商品简要信息"""
    return {
        "id": product.id,
        "platform_product_id": product.platform_product_id,
        "title": product.title,
        "price": product.price,
        "stock": product.stock,
        "in_stock": (product.stock or 0) > 0,
        "platform": product.platform,
    }


def _product_detail(product) -> dict:
    """商品完整详情"""
    return {
        "id": product.id,
        "platform": product.platform,
        "platform_product_id": product.platform_product_id,
        "title": product.title,
        "price": product.price,
        "stock": product.stock,
        "in_stock": (product.stock or 0) > 0,
        "stock_level": _stock_level(product.stock or 0),
        "specs": product.specs,
        "images": product.images,
        "shipping_info": product.shipping_info,
        "description": product.description,
        "last_synced_at": (
            product.last_synced_at.isoformat()
            if product.last_synced_at
            else None
        ),
        "created_at": (
            product.created_at.isoformat()
            if product.created_at
            else None
        ),
    }


def _stock_level(total: int) -> str:
    """库存富文本描述"""
    if total <= 0:
        return "缺货"
    if total <= 5:
        return "库存紧张（≤5件）"
    if total <= 20:
        return "少量库存（6-20件）"
    if total <= 100:
        return "库存充足（21-100件）"
    return "库存充裕（>100件）"


def _match_sku_stock(
    specs: dict, sku: str, total_stock: int
) -> dict:
    """
    根据 SKU 描述字符串（如 "颜色:红色,尺码:M"）判断库存状态。

    匹配逻辑：解析 sku → 与 specs 中各维度比对 → 若全部匹配则标记有货。
    返回 {"in_stock": bool, "level": str}
    """
    if not specs:
        return {
            "in_stock": total_stock > 0,
            "level": _stock_level(total_stock),
        }

    # 解析 sku 字符串 → {维度: 值}
    pairs = {}
    for part in re.split(r"[,，;；\s]+", sku):
        part = part.strip()
        if not part:
            continue
        sep = ":" if ":" in part else "：" if "：" in part else None
        if not sep:
            continue
        k, v = part.split(sep, 1)
        pairs[k.strip()] = v.strip()

    if not pairs:
        return {
            "in_stock": total_stock > 0,
            "level": _stock_level(total_stock),
        }

    # 检查 specs 中是否包含该维度/值
    matched = True
    for dim, val in pairs.items():
        # 尝试中英文维度名
        options = specs.get(dim) or specs.get(_reverse_dim(dim))
        if options:
            if isinstance(options, list):
                if val not in options and not any(
                    val in str(o) for o in options
                ):
                    matched = False
                    break
            elif isinstance(options, str):
                if val not in options:
                    matched = False
                    break

    in_stock = matched and total_stock > 0
    return {
        "in_stock": in_stock,
        "level": _stock_level(total_stock) if in_stock else "缺货",
    }


def _reverse_dim(dim: str) -> str:
    """中英文维度名互转"""
    mapping = {
        "颜色": "color",
        "color": "颜色",
        "尺码": "size",
        "size": "尺码",
        "规格": "spec",
        "spec": "规格",
        "尺寸": "size",
        "款式": "style",
        "style": "款式",
    }
    return mapping.get(dim, dim)


def _extract_shipping_from_description(desc: str) -> str:
    """从商品描述中提取物流相关文字片段"""
    if not desc:
        return ""
    patterns = [
        r"(发货[^。！\n]{0,80})",
        r"(快递[^。！\n]{0,80})",
        r"(包邮[^。！\n]{0,80})",
        r"(物流[^。！\n]{0,80})",
        r"(时效[^。！\n]{0,80})",
        r"(配送[^。！\n]{0,80})",
    ]
    snippets = []
    for p in patterns:
        m = re.search(p, desc)
        if m:
            snippets.append(m.group(1))
    return "；".join(snippets) if snippets else ""


def _extract_size_from_description(desc: str) -> str:
    """从商品描述中提取尺码/尺寸相关文字"""
    if not desc:
        return ""
    patterns = [
        r"(尺码[^。！\n]{0,200})",
        r"(尺寸[^。！\n]{0,200})",
        r"(胸围[^。！\n]{0,100})",
        r"(衣长[^。！\n]{0,100})",
        r"(建议[^。！\n]{0,150}?(?:身高|体重)[^。！\n]{0,50})",
    ]
    snippets = []
    for p in patterns:
        m = re.search(p, desc)
        if m:
            snippets.append(m.group(1))
    return "；".join(snippets) if snippets else ""


def _extract_material_from_description(desc: str) -> tuple:
    """
    从商品描述中提取面料/材质 + 洗护说明。

    Returns: (fabric_str, care_str)
    """
    fabric = ""
    care = ""
    if not desc:
        return fabric, care

    # 面料成分
    fabric_patterns = [
        r"(面料[成分]?[：:][^。！\n]{0,200})",
        r"(材质[：:][^。！\n]{0,200})",
        r"(成分[：:][^。！\n]{0,200})",
        r"(\d+%[棉麻丝毛涤纶氨纶莫代尔天丝粘胶锦纶腈纶][^。！\n]{0,100})",
    ]
    for p in fabric_patterns:
        m = re.search(p, desc)
        if m:
            fabric = m.group(1)
            break

    # 洗护说明
    care_patterns = [
        r"(洗[涤护][^。！\n]{0,150})",
        r"(保养[^。！\n]{0,150})",
        r"(不可[漂烘干][^。！\n]{0,50})",
        r"(手洗[^。！\n]{0,80})",
        r"(机洗[^。！\n]{0,80})",
        r"(干洗[^。！\n]{0,80})",
        r"(水温[^。！\n]{0,80})",
    ]
    snippets = []
    for p in care_patterns:
        for m in re.finditer(p, desc):
            snippets.append(m.group(1))
    care = "；".join(snippets[:3]) if snippets else ""

    return fabric, care
