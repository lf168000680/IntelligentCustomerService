from .base import BaseTool, ToolResult, ToolRegistry
from .web_search import WebSearchTool
from .knowledge_base import KnowledgeBaseTool
from .customer_memory import CustomerMemoryTool
from .product_lookup import ProductLookupTool
from .image_analysis import ImageAnalysisTool

registry = ToolRegistry()

async def init_tools(db_factory=None, llm_router=None):
    """Initialize and register all agent tools"""
    registry.register(WebSearchTool())
    if db_factory:
        registry.register(KnowledgeBaseTool(db_factory=db_factory))
        registry.register(CustomerMemoryTool(db_factory=db_factory))
        registry.register(ProductLookupTool(db_factory=db_factory))
    if llm_router:
        registry.register(ImageAnalysisTool(llm_router=llm_router))
    return registry

def get_tools_for_llm(provider_type: str):
    """Get tools in the correct schema format for a given provider"""
    if provider_type == "anthropic":
        return registry.to_anthropic_tools()
    else:
        return registry.to_openai_tools()
