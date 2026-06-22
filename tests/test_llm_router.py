"""LLM Router 单元测试"""
import pytest
from server.llm.base import LLMRequest
from server.llm.router import LLMRouter


def test_router_init():
    router = LLMRouter()
    assert len(router.all_entries) == 0
    assert len(router.providers) == 0


def test_router_status_empty():
    router = LLMRouter()
    status = router.get_status()
    assert status == {}
