"""Persona Builder 单元测试"""
import pytest
from server.engine.persona import PersonaBuilder, get_persona


def test_load_default_persona():
    persona = get_persona("default")
    assert persona is not None
    assert len(persona.soul) > 0
    assert len(persona.style) > 0
    assert len(persona.skill) > 0


def test_build_system_prompt():
    persona = get_persona("default")
    prompt = persona.build_system_prompt()
    assert len(prompt) > 100
    assert "小糖" in prompt
    assert "糖の衣橱" in prompt


def test_to_dict():
    persona = get_persona("default")
    data = persona.to_dict()
    assert "SOUL.md" in data
    assert "STYLE.md" in data
    assert "SKILL.md" in data
    assert "MEMORY.md" in data
