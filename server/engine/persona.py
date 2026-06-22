"""
Persona Builder — 将 SOUL/STYLE/SKILL/MEMORY/RULES 编译为 System Prompt
支持从文件热加载 + 从数据库读取
"""
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any

from loguru import logger

PROJECT_ROOT = Path(__file__).parent.parent.parent
PERSONAS_DIR = PROJECT_ROOT / "config" / "personas"


class PersonaBuilder:
    """
    人格文档编译器

    加载 SOUL.md / STYLE.md / SKILL.md / MEMORY.md / RULES.md
    编译为完整的 system prompt
    """

    def __init__(self, persona_name: str = "default"):
        self.persona_name = persona_name
        self.persona_dir = PERSONAS_DIR / persona_name

        self.soul = ""
        self.style = ""
        self.skill = ""
        self.memory = ""
        self.rules = ""

        self._loaded = False

    # ── 加载 ──────────────────────────────────────

    def load_from_files(self) -> "PersonaBuilder":
        """从文件系统加载人设文档"""
        if not self.persona_dir.exists():
            logger.warning(f"Persona dir not found: {self.persona_dir}, using default")
            self.persona_dir = PERSONAS_DIR / "default"
            if not self.persona_dir.exists():
                logger.error("Default persona not found!")
                return self

        self.soul = self._read("SOUL.md")
        self.style = self._read("STYLE.md")
        self.skill = self._read("SKILL.md")
        self.memory = self._read("MEMORY.md")
        self.rules = self._read("RULES.md", required=False)

        self._loaded = True
        logger.info(f"Persona '{self.persona_name}' loaded from files")
        return self

    def load_from_dict(self, data: Dict[str, str]) -> "PersonaBuilder":
        """从字典加载人设 (数据库读取)"""
        self.soul = data.get("SOUL.md", "")
        self.style = data.get("STYLE.md", "")
        self.skill = data.get("SKILL.md", "")
        self.memory = data.get("MEMORY.md", "")
        self.rules = data.get("RULES.md", "")
        self._loaded = True
        return self

    @classmethod
    async def load_from_db(cls, db_session, persona_name: str = "default") -> "PersonaBuilder":
        """从数据库加载人设"""
        from ..db.models import PersonaRecord
        from sqlalchemy import select

        result = await db_session.execute(
            select(PersonaRecord).where(PersonaRecord.name == persona_name)
        )
        record = result.scalar_one_or_none()

        if record and record.files:
            return cls(persona_name).load_from_dict(record.files)

        # 降级到文件系统
        return cls(persona_name).load_from_files()

    # ── 编译 ──────────────────────────────────────

    def build_system_prompt(self,
                            context: Dict[str, Any] = None,
                            knowledge_snippets: List[str] = None,
                            relevant_memories: List[str] = None) -> str:
        """
        动态构建 system prompt

        结构:
        1. SOUL — 身份 + 价值观 (固定)
        2. STYLE — 话术规范 (固定)
        3. SKILL — 能力边界 (固定)
        4. MEMORY — 相关记忆条目 (动态注入)
        5. 知识库检索结果 (动态)
        6. RULES — 行为约束 (固定)
        7. 当前上下文信息
        """
        if not self._loaded:
            self.load_from_files()

        context = context or {}
        parts = []

        # ── Part 1: 核心身份 ──
        if self.soul:
            parts.append(self.soul)

        # ── Part 2: 沟通风格 ──
        if self.style:
            parts.append("\n\n---\n\n## 沟通风格\n" + self.style)

        # ── Part 3: 专业能力 ──
        if self.skill:
            parts.append("\n\n---\n\n## 专业能力\n" + self.skill)

        # ── Part 4: 相关记忆 ──
        mem_entries = relevant_memories or []
        # 也提取 MEMORY.md 中与当前 context 相关的条目
        context_memories = self._extract_context_memories(context)
        mem_entries.extend(context_memories)

        if mem_entries:
            parts.append("\n\n---\n\n## 相关记忆\n\n" + "\n".join(mem_entries[:5]))

        # ── Part 5: 知识库检索结果 ──
        if knowledge_snippets:
            parts.append("\n\n---\n\n## 参考知识 (据此回答)\n")
            for i, snippet in enumerate(knowledge_snippets[:5], 1):
                clean = snippet.strip()[:800]  # 截断避免太长
                parts.append(f"\n【资料{i}】\n{clean}")

        # ── Part 6: 行为规则 ──
        if self.rules:
            parts.append("\n\n---\n\n## 行为规则\n" + self.rules)

        # ── Part 7: 上下文信息 ──
        context_block = self._build_context_block(context)
        if context_block:
            parts.append(f"\n\n---\n{context_block}")

        # ── 最终输出要求 ──
        parts.append("""

---
## 输出要求
- 严格遵守上面的沟通风格，包括语气、节奏、emoji使用习惯
- 你不主动暴露自己是AI。你是真人客服
- 如果没有相关知识，说"我帮你问下确认下哦"，绝对不编造
- 不确定的事情不要乱说，宁可说不知道然后帮客户确认
- 需要转人工处理的事情，引导客户稍等，说明已经标记给老板处理
- 语言自然、口语化，不要用书面语
""")

        return "\n".join(parts)

    def build_minimal_prompt(self) -> str:
        """构建最小 system prompt (用于 cheap 模型，减少 token)"""
        if not self._loaded:
            self.load_from_files()

        parts = []
        if self.soul:
            parts.append(self.soul)
        if self.style:
            # 只取关键段落
            lines = self.style.split("\n")
            key_lines = [l for l in lines if l.startswith("##") or l.startswith("- **") or l.startswith("✅")]
            parts.append("\n## 沟通风格\n" + "\n".join(key_lines[:20]))
        if self.rules:
            parts.append("\n## 行为规则\n" + self.rules)

        return "\n".join(parts)

    # ── 动态更新 ──────────────────────────────────

    async def update_memory(self,
                            db_session,
                            entry: str,
                            category: str = "general",
                            auto_commit: bool = True) -> str:
        """
        动态追加记忆条目到 MEMORY.md

        触发时机:
        - 对话结束后的总结
        - 检测到客户新偏好
        - 运营手动添加
        - 商品信息变更
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        memory_entry = f"- {timestamp}: [{category}] {entry}"

        # 追加到文件
        memory_file = self.persona_dir / "MEMORY.md"
        if memory_file.exists():
            content = memory_file.read_text(encoding="utf-8")
            content = content.rstrip() + f"\n{memory_entry}\n"
        else:
            content = f"# MEMORY.md — 长期记忆\n\n{memory_entry}\n"

        memory_file.write_text(content, encoding="utf-8")
        self.memory = content

        # 同步到数据库
        if auto_commit and db_session:
            try:
                from ..db.models import PersonaRecord
                from sqlalchemy import select, update
                result = await db_session.execute(
                    select(PersonaRecord).where(PersonaRecord.name == self.persona_name)
                )
                record = result.scalar_one_or_none()
                if record:
                    files = dict(record.files)
                    files["MEMORY.md"] = content
                    record.files = files
                    await db_session.commit()
            except Exception as e:
                logger.warning(f"Failed to sync memory to DB: {e}")

        return memory_entry

    async def update_memory_from_conversations(self,
                                                db_session,
                                                conversations: List[Dict]) -> List[str]:
        """
        从对话中自动提取记忆并更新

        提取内容:
        - 客户显性偏好 (尺码、风格、颜色)
        - 老客户识别 (多次回购)
        - 新发现的问题模式
        """
        # 这里需要 LLM 协助提取，在 knowledge pipeline 中调用
        entries = []
        # ... (由 KnowledgeLearningPipeline 调用 LLM 处理后传入)
        return entries

    # ── 内部方法 ──────────────────────────────────

    def _read(self, filename: str, required: bool = True) -> str:
        """读取人设文件"""
        filepath = self.persona_dir / filename
        if filepath.exists():
            return filepath.read_text(encoding="utf-8")
        if required:
            logger.warning(f"Persona file not found: {filepath}")
        return ""

    def _extract_context_memories(self, context: Dict[str, Any]) -> List[str]:
        """
        从 MEMORY.md 中提取与当前对话相关的条目

        简单策略:
        - 关键词匹配
        - 最近 7 天的「重要事件」
        - 老客户档案匹配
        """
        if not self.memory:
            return []

        entries = []
        user_id = context.get("user_id", "")
        user_name = context.get("user_name", "")
        intent = context.get("intent", "")

        # 检查老客户档案
        if user_id or user_name:
            for line in self.memory.split("\n"):
                if user_id and user_id in line:
                    entries.append(line.strip("- "))
                elif user_name and user_name in line:
                    entries.append(line.strip("- "))

        # 检查最近事件 (日期匹配)
        import re
        today = datetime.now()
        for line in self.memory.split("\n"):
            match = re.search(r'(\d{4}-\d{2}-\d{2})', line)
            if match:
                try:
                    event_date = datetime.strptime(match.group(1), "%Y-%m-%d")
                    if (today - event_date).days <= 30:
                        if not any(e.strip("- ") == line.strip("- ") for e in entries):
                            entries.append(line.strip("- "))
                except ValueError:
                    pass

        return entries

    def _build_context_block(self, context: Dict[str, Any]) -> str:
        """构建上下文信息块"""
        parts = ["## 当前会话上下文"]

        # 时间
        now = datetime.now()
        parts.append(f"- 当前时间: {now.strftime('%Y-%m-%d %H:%M')} (星期{'一二三四五六日'[now.weekday()]})")

        # 客户信息
        user_name = context.get("user_name", "")
        if user_name:
            parts.append(f"- 正在与客户「{user_name}」对话")

        # 客户画像
        preferences = context.get("preferences", {})
        if preferences:
            parts.append(f"- 客户偏好: {preferences}")

        # 对话历史轮次
        history_turns = context.get("history_turns", 0)
        if history_turns:
            parts.append(f"- 本次已对话 {history_turns} 轮")

        # 商品上下文
        product = context.get("product")
        if product:
            parts.append(f"- 当前讨论的商品: {product.get('title', '')} (¥{product.get('price', '')})")

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, str]:
        """导出为字典 (用于存储到数据库)"""
        return {
            "SOUL.md": self.soul,
            "STYLE.md": self.style,
            "SKILL.md": self.skill,
            "MEMORY.md": self.memory,
            "RULES.md": self.rules,
        }

    def reload(self) -> "PersonaBuilder":
        """重新加载"""
        self._loaded = False
        return self.load_from_files()


# 全局默认 Persona 实例 (懒加载)
_default_persona = None

def get_persona(name: str = "default") -> PersonaBuilder:
    """获取 Persona 实例"""
    global _default_persona
    if name == "default" and _default_persona is not None:
        return _default_persona
    builder = PersonaBuilder(name).load_from_files()
    if name == "default":
        _default_persona = builder
    return builder
