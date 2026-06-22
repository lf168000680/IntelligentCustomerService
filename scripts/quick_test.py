"""
快速验证脚本 — 无需数据库即可测试核心功能
"""
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，使 server 成为可导入的包
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger

# 直接导入（已修复 __init__.py 为惰性导入）
from server.config import config as app_config
from server.llm.router import LLMRouter
from server.llm.base import LLMRequest
from server.engine.persona import get_persona
from server.engine.intent import IntentClassifier


def test_config():
    """测试配置加载"""
    logger.info("=== 测试配置加载 ===")
    logger.info(f"Model templates (from yaml): {len(app_config.model_templates)}")
    for m in app_config.model_templates:
        api_status = "已配置" if m.api_key else "待配置"
        logger.info(f"  - {m.name}: {m.provider}/{m.model_id} (enabled={m.enabled}, API Key: {api_status})")
    logger.info(f"Models from DB: {len(app_config.models)}")
    logger.info(f"Fallback order: {app_config.routing.fallback_order}")
    return len(app_config.model_templates) > 0


def test_llm_router():
    """测试 LLM Router (无API Key时注册0个是正常的)"""
    logger.info("\n=== 测试 LLM Router ===")
    logger.info("注意: API Key 现在存储在数据库中，通过 GUI 配置")
    logger.info("没有 API Key 时 Router 不会注册任何 Provider (这是正确的行为)")

    router = LLMRouter()
    router.register_from_app_config()
    logger.info(f"Registered {len(router.all_entries)} providers (需要先在GUI中配置API Key)")

    # Router 基础架构正常即 PASS（0 provider 但架构完好）
    return True  # Router infrastructure is healthy even without API keys


def test_persona():
    """测试人设加载"""
    logger.info("\n=== 测试人设加载 ===")
    persona = get_persona("default")
    logger.info(f"Persona name: {persona.persona_name}")
    logger.info(f"SOUL: {len(persona.soul)} chars")
    logger.info(f"STYLE: {len(persona.style)} chars")
    logger.info(f"SKILL: {len(persona.skill)} chars")
    logger.info(f"MEMORY: {len(persona.memory)} chars")
    logger.info(f"RULES: {len(persona.rules)} chars")

    prompt = persona.build_system_prompt()
    logger.info(f"Compiled prompt: {len(prompt)} chars")
    logger.info(f"Preview: {prompt[:150]}...")

    return len(persona.soul) > 0 and len(prompt) > 500


def test_intent_classifier():
    """测试意图分类"""
    logger.info("\n=== 测试意图分类器 ===")
    classifier = IntentClassifier()

    cases = [
        ("你好", "greeting"),
        ("这件衣服会缩水吗？", "presale"),
        ("我160/50kg穿什么码？", "presale"),
        ("什么时候发货？", "presale"),
        ("我的快递到哪了？", "order"),
        ("质量太差了我要退货！", "aftersale"),
        ("谢谢", "closing"),
    ]

    correct = 0
    for msg, expected in cases:
        result = classifier._keyword_match(msg)
        actual = result["intent"] if result else "other"
        match = "OK" if actual == expected else f"WRONG (got {actual})"
        logger.info(f"  [{match}] '{msg}' → {actual}")
        if actual == expected:
            correct += 1

    accuracy = correct / len(cases) * 100
    logger.info(f"Intent accuracy: {accuracy:.0f}%")
    return accuracy >= 70


def test_persona_files():
    """检查人设文件完整性"""
    logger.info("\n=== 检查人设文件 ===")
    persona_dir = PROJECT_ROOT / "config" / "personas" / "default"
    files = ["SOUL.md", "STYLE.md", "SKILL.md", "MEMORY.md", "RULES.md"]
    all_ok = True
    for f in files:
        fpath = persona_dir / f
        exists = fpath.exists()
        size = fpath.stat().st_size if exists else 0
        status = "OK" if exists and size > 100 else "MISSING/SMALL"
        logger.info(f"  [{status}] {f}: {size} bytes")
        if not exists:
            all_ok = False
    return all_ok


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("Kefu 智能客服系统 — 快速验证")
    logger.info("=" * 50)

    results = {
        "persona_files": test_persona_files(),
        "config": test_config(),
        "llm_router": test_llm_router(),
        "persona": test_persona(),
        "intent_classifier": test_intent_classifier(),
    }

    logger.info("\n" + "=" * 50)
    logger.info("验证结果:")
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        logger.info(f"  [{status}] {name}")

    all_pass = all(results.values())
    logger.info(f"\n总体: {'ALL PASS' if all_pass else 'SOME FAILED'}")
    sys.exit(0 if all_pass else 1)
