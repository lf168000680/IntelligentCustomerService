from .base import BaseTool, ToolResult, ToolRegistry
from .web_search import WebSearchTool
from .knowledge_base import KnowledgeBaseTool
from .customer_memory import CustomerMemoryTool
from .product_lookup import ProductLookupTool
from .image_analysis import ImageAnalysisTool

registry = ToolRegistry()

async def init_tools(db_factory=None, llm_router=None):
    """Initialize and register all agent tools"""
    await registry.register(WebSearchTool())
    if db_factory:
        await registry.register(KnowledgeBaseTool(db_factory=db_factory))
        await registry.register(CustomerMemoryTool(db_factory=db_factory))
        await registry.register(ProductLookupTool(db_factory=db_factory))
    if llm_router:
        await registry.register(ImageAnalysisTool(llm_router=llm_router))
    return registry

async def get_tools_for_llm(provider_type: str):
    """Get tools in the correct schema format for a given provider"""
    if provider_type == "anthropic":
        return await registry.to_anthropic_tools()
    else:
        return await registry.to_openai_tools()
