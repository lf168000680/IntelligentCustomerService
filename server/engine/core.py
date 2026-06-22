"""
AI 核心引擎 — 意图识别 → 知识检索 → 回复生成
完整对话处理管线
"""
import json
import random
import time
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from loguru import logger

from .intent import IntentClassifier
from .persona import get_persona, PersonaBuilder

# RAGRetriever 需要数据库，惰性导入
RAGRetriever = None
try:
    from .rag import RAGRetriever as _RAG
    RAGRetriever = _RAG
except ImportError:
    pass
from ..llm.base import LLMRequest
from ..llm.router import LLMRouter


class CoreEngine:
    """
    智能客服 AI 引擎

    处理流程:
    1. 接收消息 + 会话上下文
    2. 意图分类
    3. RAG 检索
    4. 构建 system prompt (Persona + Knowledge)
    5. LLM 生成回复
    6. 人设校验 + 后处理
    7. 返回回复 + 元数据
    """

    def __init__(self,
                 llm_router: LLMRouter,
                 db_session_factory=None,
                 persona_name: str = "default",
                 tools_enabled: bool = True):
        self.router = llm_router
        self.db_factory = db_session_factory
        self.intent_classifier = IntentClassifier(llm_router)
        self.persona: Optional[PersonaBuilder] = None
        self.tools_enabled = tools_enabled

        # 加载人设
        self.persona = get_persona(persona_name)

        # 场景 → 模型标签
        self.scene_mapping = {
            "presale": "default",
            "order": "fast",
            "aftersale": "reasoning",
            "greeting": "fast",
            "closing": "fast",
            "other": "default",
        }

        # 意图 → 工具路由
        self._intent_tool_map = {
            "查订单": ["product_lookup", "customer_memory"],
            "售后": ["image_analysis", "knowledge_base"],
            "产品咨询": ["knowledge_base", "web_search", "product_lookup"],
            "闲聊": [],
        }

    # ── 主处理流程 ──────────────────────────────────

    async def process(self,
                      message: str,
                      context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        处理单条客户消息

        Args:
            message: 客户消息文本
            context: 会话上下文
                {
                    "conversation_id": "...",
                    "user_id": "...",
                    "user_name": "...",
                    "shop_id": "...",
                    "platform": "taobao",
                    "history": [{"role": "...", "content": "..."}, ...],
                    "user_profile": {...},
                    "product": {...} or None,
                }

        Returns:
            {
                "reply": "回复文本",
                "intent": "presale",
                "confidence": 0.95,
                "knowledge_used": [...],
                "escalate": False,
                "metadata": {...}
            }
        """
        context = context or {}
        start_time = time.time()

        # ── Step 1: 意图分类 ──
        intent_result = await self.intent_classifier.classify(message)
        logger.debug(f"Intent: {intent_result}")

        # ── Step 2: 检查是否转人工 ──
        history = context.get("history", [])
        turn_count = len([m for m in history if m.get("role") == "user"])
        escalate, escalate_reason = self.intent_classifier.is_escalation_needed(
            intent_result, turn_count
        )

        if escalate:
            return {
                "reply": self._escalation_reply(escalate_reason),
                "intent": intent_result.get("intent"),
                "confidence": intent_result.get("confidence", 0.5),
                "knowledge_used": [],
                "escalate": True,
                "escalate_reason": escalate_reason,
                "metadata": {"processing_time": round(time.time() - start_time, 2)},
            }

        # ── Step 2.5: 缓存检查 (三级缓存) ──
        intent_name = intent_result.get("intent", "other")
        cache_hit = None
        try:
            from ..cache import cache_manager
            cache_hit = await cache_manager.get_exact(
                message, intent=intent_name,
                persona=self.persona.persona_name if self.persona else "default",
            )
            if cache_hit:
                processing_time = round(time.time() - start_time, 2)
                logger.debug(f"Cache HIT: intent={intent_name}, time={processing_time}s")
                return {
                    "reply": cache_hit,
                    "intent": intent_name,
                    "sub_intent": intent_result.get("sub_intent"),
                    "sentiment": intent_result.get("sentiment"),
                    "confidence": intent_result.get("confidence", 0.5),
                    "knowledge_used": [],
                    "escalate": False,
                    "scene": "cache",
                    "method": "cached",
                    "metadata": {
                        "processing_time": processing_time,
                        "source": "cache",
                        "persona": self.persona.persona_name if self.persona else "default",
                    },
                }
        except Exception as e:
            logger.debug(f"Cache check skipped: {e}")

        # ── Step 3: RAG 检索 ──
        # 需要 DB session
        knowledge_snippets = []
        knowledge_used = []

        if self.db_factory:
            async with self.db_factory() as db:
                retriever = RAGRetriever(db, self.router)
                filters = {}
                if context.get("product"):
                    filters["product_id"] = context["product"].get("id")

                kb_hits = await retriever.retrieve(
                    query=message,
                    top_k=5,
                    filters=filters,
                )
                knowledge_snippets = [h.get("answer", h.get("content", "")) for h in kb_hits]
                knowledge_used = [{
                    "id": h.get("knowledge_id"),
                    "question": h.get("question"),
                    "score": h.get("score"),
                    "source": h.get("source"),
                } for h in kb_hits]
        else:
            # 无 DB 时尝试只从向量检索 (如果有独立的向量连接)
            logger.warning("No DB session factory, skipping RAG")

        # ── Step 4: 构建 System Prompt ──
        # 提取相关记忆
        relevant_memories = self._extract_relevant_memories(context, intent_result)

        system_prompt = self.persona.build_system_prompt(
            context={
                **context,
                "intent": intent_result.get("intent"),
                "history_turns": turn_count,
            },
            knowledge_snippets=knowledge_snippets,
            relevant_memories=relevant_memories,
        )

        # ── Step 5: 构建对话 messages ──
        messages = self._build_messages(message, history)

        # ── Step 6: 工具增强处理 (若启用且意图匹配) ──
        intent_name = intent_result.get("intent", "")
        tool_names = self._get_tools_for_intent(intent_name)

        if self.tools_enabled and tool_names:
            tool_reply = await self._process_with_tools(
                message, context, intent_result, knowledge_snippets
            )
            if tool_reply is not None:
                reply = tool_reply
                # 后处理
                reply = self._post_process(reply, intent_result)
                processing_time = round(time.time() - start_time, 2)
                logger.info(f"Processed message with tools in {processing_time}s, intent={intent_name}")
                return {
                    "reply": reply,
                    "intent": intent_result.get("intent"),
                    "sub_intent": intent_result.get("sub_intent"),
                    "sentiment": intent_result.get("sentiment"),
                    "confidence": intent_result.get("confidence", 0.5),
                    "knowledge_used": knowledge_used,
                    "escalate": False,
                    "scene": "tool_enhanced",
                    "method": intent_result.get("method", "keyword"),
                    "metadata": {
                        "processing_time": processing_time,
                        "model_tag": "tool_enhanced",
                        "persona": self.persona.persona_name,
                        "tools_used": tool_names,
                    },
                }

        # ── Step 7: LLM 生成 (标准路径) ──
        scene = self.scene_mapping.get(intent_result.get("intent", "other"), "default")

        request = LLMRequest(
            messages=messages,
            system_prompt=system_prompt,
            temperature=0.7 if scene in ("default", "reasoning") else 0.5,
            max_tokens=2048 if scene == "reasoning" else 1024,
            preferred_tag=scene,
        )

        try:
            reply = await self.router.generate(request, scene)
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            # 降级回复
            reply = self._fallback_reply(message)

        # ── Step 7: 后处理 ──
        reply = self._post_process(reply, intent_result)

        # ── Step 7.5: 存入缓存 ──
        try:
            from ..cache import cache_manager
            intent_name = intent_result.get("intent", "other")
            await cache_manager.set_exact(
                message, reply,
                intent=intent_name,
                persona=self.persona.persona_name if self.persona else "default",
            )
        except Exception as e:
            logger.debug(f"Cache store skipped: {e}")

        # ── Step 8: 返回 ──
        processing_time = round(time.time() - start_time, 2)
        logger.info(f"Processed message in {processing_time}s, intent={intent_result.get('intent')}, scene={scene}")

        return {
            "reply": reply,
            "intent": intent_result.get("intent"),
            "sub_intent": intent_result.get("sub_intent"),
            "sentiment": intent_result.get("sentiment"),
            "confidence": intent_result.get("confidence", 0.5),
            "knowledge_used": knowledge_used,
            "escalate": False,
            "scene": scene,
            "method": intent_result.get("method", "keyword"),
            "metadata": {
                "processing_time": processing_time,
                "model_tag": scene,
                "persona": self.persona.persona_name,
                "cached": False,
            },
        }

    # ── 快捷方法 ──────────────────────────────────

    async def quick_reply(self, message: str) -> str:
        """快速回复 (无上下文)"""
        result = await self.process(message)
        return result["reply"]

    async def test_persona(self, message: str) -> str:
        """人设测试 (无 RAG)"""
        system = self.persona.build_system_prompt()
        msgs = [{"role": "user", "content": message}]
        req = LLMRequest(messages=msgs, system_prompt=system)
        return await self.router.generate(req, "default")

    # ── 内部方法 ──────────────────────────────────

    def _build_messages(self, current_message: str, history: List[Dict]) -> List[Dict]:
        """构建 messages 列表"""
        messages = []

        # 加入最近历史 (限制 10 轮)
        recent_history = history[-20:]  # 20 条消息 ≈ 10 轮
        for h in recent_history:
            role = "assistant" if h.get("role") in ("assistant", "system") else "user"
            messages.append({"role": role, "content": h.get("content", "")})

        # 当前消息
        messages.append({"role": "user", "content": current_message})

        return messages

    def _extract_relevant_memories(self, context: Dict, intent_result: Dict) -> List[str]:
        """从上下文提取相关记忆条目"""
        memories = []

        intent = intent_result.get("intent", "")
        user_profile = context.get("user_profile", {})

        # 老客户
        if user_profile:
            pref_tags = user_profile.get("tags", [])
            if "老客户" in pref_tags or "VIP" in pref_tags:
                memories.append(f"- 该客户为{user_profile.get('tags')}，购买{user_profile.get('order_count', 0)}次，累计消费¥{user_profile.get('total_spent', 0)}")
            if user_profile.get("preferences"):
                memories.append(f"- 客户偏好: {user_profile['preferences']}")

        # 新客户 + 售后 → 特别注意
        if intent == "aftersale" and (not user_profile or user_profile.get("order_count", 0) <= 1):
            memories.append("- ⚠️ 新客户售后问题，需格外耐心 + 引导拍照确认问题")

        return memories[:3]

    def _post_process(self, reply: str, intent_result: Dict) -> str:
        """回复后处理"""
        # 截断过长的回复 (真人不会发太长)
        if len(reply) > 600:
            # 在合适的位置截断
            for sep in ["。", "！", "？", "\n", ". ", "! ", "? "]:
                idx = reply[:600].rfind(sep)
                if idx > 300:
                    reply = reply[:idx + 1]
                    break
            else:
                reply = reply[:500] + "..."

        # 去除 "我是AI" / "我是助手" 之类的词
        ai_patterns = [
            "我是AI", "我是人工智能", "我是机器人", "我是助手",
            "作为AI", "作为人工智能", "根据我的训练",
        ]
        for pattern in ai_patterns:
            if pattern in reply:
                # 替换为自然的表达
                reply = reply.replace(pattern, "")
                if not reply.strip():
                    reply = "好哒亲亲～还有什么可以帮你的吗？"

        return reply.strip()

    def _escalation_reply(self, reason: str) -> str:
        """转人工时的话术"""
        replies = [
            "亲亲，这个问题我帮你转给老板处理哦～稍等一下，老板看到马上回复你！☺️",
            "这个问题有点特殊呢，我标记给老板亲自处理了，稍等下哦～💕",
            "好的宝，这个需要老板来确认下，我已经标记好了，他看到了就回你～",
            "我先把情况反馈给老板，他会给你处理好的，别担心呀～😊",
        ]
        return random.choice(replies)

    def _fallback_reply(self, message: str) -> str:
        """LLM 失败时的降级回复"""
        if any(w in message for w in ["你好", "在吗", "在么"]):
            return "来啦来啦～有什么想了解的尽管问！😊"
        elif any(w in message for w in ["谢谢", "好的"]):
            return "不客气呀～还有什么想了解的随时找我！💕"
        else:
            return "稍等哦亲亲，正在帮你查～ 😊"

    # ── 工具增强处理 ──────────────────────────────────

    def _get_tools_for_intent(self, intent: str) -> List[str]:
        """根据意图返回应启用的工具名列表。

        Returns:
            工具名称列表，空列表表示意图明确无需工具 (如闲聊)。
            ``None`` 表示意图不在工具路由表中，走标准LLM路径。
        """
        # 精确匹配
        if intent in self._intent_tool_map:
            return self._intent_tool_map[intent]
        # 模糊匹配前缀
        for key, tools in self._intent_tool_map.items():
            if intent.startswith(key) or key.startswith(intent):
                return tools
        # 未匹配到路由表 — 返回 None 表示不走工具路径
        return None

    async def _process_with_tools(
        self,
        message: str,
        context: Dict[str, Any],
        intent_result: Dict[str, Any],
        knowledge_snippets: List[str],
    ) -> Optional[str]:
        """工具增强处理管线。

        1. 根据意图确定工具集
        2. 构建含工具指引的 system prompt
        3. 获取工具 JSON Schema
        4. 进入 tool-use 循环: 发送 → 检测 tool_use → 执行工具 → 回传结果
        5. 返回最终文本回复，None 表示回退到标准路径
        """
        intent = intent_result.get("intent", "")
        tool_names = self._get_tools_for_intent(intent)

        if not tool_names:
            return None

        # 检查是否有可用的 DB 连接 (大多数工具需要)
        if not self.db_factory:
            logger.warning("Tools requested but no db_factory available, falling back")
            return None

        # ── 获取工具 registry ──
        try:
            from ..tools import registry as tool_registry
        except ImportError:
            logger.warning("Tools module not available, falling back")
            return None

        # ── 检查目标工具是否已注册 ──
        available = []
        for name in tool_names:
            if await tool_registry.has_tool(name):
                available.append(name)
            else:
                logger.debug(f"Tool '{name}' not registered, skipping")

        if not available:
            logger.debug("None of the intended tools are registered, falling back")
            return None

        # ── 获取活跃 provider 类型 ──
        provider_type = self._get_active_provider_type()

        # ── 获取工具 JSON Schema ──
        if provider_type == "anthropic":
            tool_schemas = await tool_registry.to_anthropic_tools(available)
        else:
            tool_schemas = await tool_registry.to_openai_tools(available)

        if not tool_schemas:
            return None

        # ── 构建 messages ──
        history = context.get("history", [])
        messages = self._build_messages(message, history)

        # ── 构建 system prompt (含工具使用指引) ──
        system_prompt = self._build_tool_system_prompt(
            context, intent_result, knowledge_snippets
        )

        # ── 进入 tool-use 循环 ──
        try:
            reply = await self._run_tool_loop(
                messages, system_prompt, tool_schemas, available, provider_type,
            )
            return reply
        except Exception as e:
            logger.error(f"Tool processing failed: {e}", exc_info=True)
            return None

    def _build_tool_system_prompt(
        self,
        context: Dict[str, Any],
        intent_result: Dict[str, Any],
        knowledge_snippets: List[str],
    ) -> str:
        """构建包含工具使用指引的 system prompt。"""
        # 先构建基础人设 prompt
        turn_count = len([
            m for m in context.get("history", []) if m.get("role") == "user"
        ])
        relevant_memories = self._extract_relevant_memories(context, intent_result)

        base_prompt = self.persona.build_system_prompt(
            context={
                **context,
                "intent": intent_result.get("intent"),
                "history_turns": turn_count,
            },
            knowledge_snippets=knowledge_snippets,
            relevant_memories=relevant_memories,
        )

        # 追加工具使用指引
        tool_guidance = (
            "\n\n---\n"
            "你拥有以下工具可以使用。当客户问题需要查询实时信息、数据库记录、或执行特定操作时，"
            "请主动调用对应工具获取准确数据，而不是凭记忆猜测。\n"
            "- 商品信息 / 库存 / 物流 → 使用 product_lookup 工具\n"
            "- 客户偏好 / 订单历史 → 使用 customer_memory 工具\n"
            "- 知识库 FAQ / 售后政策 → 使用 knowledge_base 工具\n"
            "- 需要联网搜索竞品、行情、政策 → 使用 web_search 工具\n"
            "- 客户上传了图片(瑕疵/上身/色差/截图) → 使用 image_analysis 工具\n\n"
            "调用工具后，根据返回的真实数据来组织回复。"
            "注意保持亲切自然的客服语气，不要直接输出 JSON 原始数据。"
        )

        return base_prompt + tool_guidance

    def _get_active_provider_type(self) -> str:
        """探测当前活跃 LLM 厂商类型，用于格式化工具 schema。"""
        for tag_entries in self.router.providers.values():
            for entry in tag_entries:
                if entry.config.enabled:
                    ptype = (entry.config.provider or "").lower()
                    if ptype in ("anthropic", "openai"):
                        return ptype
                    # openai_compat / custom 用 OpenAI 格式
                    return "openai"
        return "openai"  # 默认

    async def _run_tool_loop(
        self,
        messages: List[Dict],
        system_prompt: str,
        tool_schemas: List[Dict],
        tool_names: List[str],
        provider_type: str,
    ) -> Optional[str]:
        """执行 tool-use 循环: 发送LLM请求 → 检测tool_use → 执行工具 → 回传结果。

        最多循环 3 轮 (防止无限循环)。
        """
        from ..tools import registry as tool_registry

        max_rounds = 3

        for round_idx in range(max_rounds):
            # ── 调用 LLM (原生 tool-use) ──
            response_text, tool_use_blocks = await self._call_llm_raw(
                messages, system_prompt, tool_schemas, provider_type,
            )

            # 纯文本回复 — 直接返回
            if response_text and not tool_use_blocks:
                return response_text

            # 无 tool_use 且无文本 — 异常
            if not tool_use_blocks:
                if round_idx == 0:
                    # 第一轮就没工具调用，可能是 LLM 选择不用工具
                    return response_text or None
                logger.warning("Tool loop: no tool_use and no text in round %d", round_idx + 1)
                return response_text

            # ── 执行工具调用 ──
            logger.info(
                f"Tool loop round {round_idx + 1}: executing {len(tool_use_blocks)} tool(s)"
            )

            tool_results = []
            for tb in tool_use_blocks:
                tool_name = tb.get("name", "")
                tool_input = tb.get("input", {})
                tool_id = tb.get("id", "")

                logger.debug(f"Calling tool: {tool_name}({tool_input})")

                try:
                    tool = await tool_registry.get_tool(tool_name)
                    result = await tool.call(**tool_input)
                    result_str = result.to_string()
                except Exception as e:
                    logger.error(f"Tool '{tool_name}' execution failed: {e}")
                    result_str = f"[工具执行失败] {tool_name}: {e}"

                tool_results.append({
                    "id": tool_id,
                    "name": tool_name,
                    "result": result_str,
                })

            # ── 将 tool_use + tool_result 编织进 messages ──
            messages = self._inject_tool_results(
                messages, tool_use_blocks, tool_results, provider_type,
            )

        logger.warning(f"Tool loop exceeded max rounds ({max_rounds}), returning last result")
        return "亲亲，我查了一下相关信息，整理好了发给你哦～"

    async def _call_llm_raw(
        self,
        messages: List[Dict],
        system_prompt: str,
        tool_schemas: List[Dict],
        provider_type: str,
    ) -> Tuple[Optional[str], List[Dict]]:
        """直接调用 LLM 原生 API，返回 (文本回复, tool_use 块列表)。

        Args:
            messages: 对话消息列表
            system_prompt: 系统提示
            tool_schemas: 工具定义 (Anthropic 或 OpenAI 格式)
            provider_type: "anthropic" | "openai" | ...

        Returns:
            (text_content, tool_use_blocks)
            - text_content: 纯文本回复 (可能为 None)
            - tool_use_blocks: [{"id": "...", "name": "...", "input": {...}}, ...]
        """
        # 获取一个可用的 provider entry
        for tag_entries in self.router.providers.values():
            for entry in tag_entries:
                if not entry.config.enabled:
                    continue
                if self.router._is_circuit_open(entry):
                    continue

                provider = entry.provider
                cfg = entry.config

                try:
                    if provider_type == "anthropic":
                        return await self._call_anthropic_with_tools(
                            provider, cfg, messages, system_prompt, tool_schemas,
                        )
                    else:
                        return await self._call_openai_with_tools(
                            provider, cfg, messages, system_prompt, tool_schemas,
                        )
                except Exception as e:
                    logger.warning(f"LLM raw call failed for {cfg.name}: {e}")
                    continue

        raise RuntimeError("No enabled provider available for tool use")

    async def _call_anthropic_with_tools(
        self,
        provider,
        cfg,
        messages: List[Dict],
        system_prompt: str,
        tool_schemas: List[Dict],
    ) -> Tuple[Optional[str], List[Dict]]:
        """Anthropic Messages API: 原生 tool-use 请求。"""
        # 转换消息为 Anthropic 格式
        converted = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content", "")
            if role == "system":
                continue
            an_role = "assistant" if role == "assistant" else "user"
            if converted and converted[-1]["role"] == an_role and isinstance(content, str):
                prev = converted[-1].get("content", "")
                if isinstance(prev, str):
                    converted[-1]["content"] = prev + "\n" + content
                    continue
            converted.append({"role": an_role, "content": content})

        kwargs: Dict[str, Any] = {"system": system_prompt} if system_prompt else {}
        kwargs["tools"] = tool_schemas
        kwargs.update(provider.api_extra if hasattr(provider, "api_extra") else {})

        resp = await provider.client.messages.create(
            model=cfg.model_id,
            max_tokens=cfg.max_tokens,
            messages=converted,
            temperature=cfg.temperature,
            **kwargs,
        )

        # 解析响应
        text_parts = []
        tool_blocks = []

        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_blocks.append({
                    "id": block.id,
                    "name": block.name,
                    "input": dict(block.input) if block.input else {},
                })

        return ("\n".join(text_parts) if text_parts else None, tool_blocks)

    async def _call_openai_with_tools(
        self,
        provider,
        cfg,
        messages: List[Dict],
        system_prompt: str,
        tool_schemas: List[Dict],
    ) -> Tuple[Optional[str], List[Dict]]:
        """OpenAI Chat Completions API: 原生 tool-calls 请求。"""
        # 构建 OpenAI 格式 messages
        oai_messages = []
        if system_prompt:
            oai_messages.append({"role": "system", "content": system_prompt})
        oai_messages.extend(messages)

        resp = await provider.client.chat.completions.create(
            model=cfg.model_id,
            messages=oai_messages,
            max_tokens=cfg.max_tokens,
            temperature=cfg.temperature,
            tools=tool_schemas,
        )

        choice = resp.choices[0]
        msg = choice.message

        text = msg.content or None
        tool_blocks = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                import json
                try:
                    args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                except json.JSONDecodeError:
                    args = {}
                tool_blocks.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": args,
                })

        return (text, tool_blocks)

    def _inject_tool_results(
        self,
        messages: List[Dict],
        tool_use_blocks: List[Dict],
        tool_results: List[Dict],
        provider_type: str,
    ) -> List[Dict]:
        """将 tool_use 请求和 tool_result 响应编织进消息历史。

        Anthropic 格式: assistant 消息含 content ToolUseBlock, 然后 user 消息含 ToolResultBlock
        OpenAI 格式: assistant 消息含 tool_calls, 然后 tool 消息含结果
        """
        extended = list(messages)  # 不修改原始列表

        if provider_type == "anthropic":
            # 构造 assistant 消息 (含 tool_use content blocks)
            assistant_content = []
            for tb in tool_use_blocks:
                assistant_content.append({
                    "type": "tool_use",
                    "id": tb["id"],
                    "name": tb["name"],
                    "input": tb["input"],
                })
            extended.append({"role": "assistant", "content": assistant_content})

            # 构造 user 消息 (含 tool_result content blocks)
            result_content = []
            for tr in tool_results:
                result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tr["id"],
                    "content": tr["result"],
                })
            extended.append({"role": "user", "content": result_content})
        else:
            # OpenAI 格式
            oai_tool_calls = []
            for tb in tool_use_blocks:
                import json
                oai_tool_calls.append({
                    "id": tb["id"],
                    "type": "function",
                    "function": {
                        "name": tb["name"],
                        "arguments": json.dumps(tb["input"], ensure_ascii=False),
                    },
                })
            extended.append({
                "role": "assistant",
                "content": None,
                "tool_calls": oai_tool_calls,
            })

            for tr in tool_results:
                extended.append({
                    "role": "tool",
                    "tool_call_id": tr["id"],
                    "content": tr["result"],
                })

        return extended
