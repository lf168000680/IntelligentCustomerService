"""
Agent Tool System — Base Classes
=================================
Inspired by WorkBuddy (Tencent) and Trae (ByteDance).

WorkBuddy design cues:
  - Rich tool metadata (tags, category, version, author).
  - Tag-based discovery and filtering.
  - Lifecycle hooks for tool composition.
  - Confirmation gating for side-effectful tools.

Trae design cues:
  - Execution middleware pipeline (before/after hooks).
  - Built-in parameter validation against JSON Schema.
  - Execution statistics for observability.
  - Timeout enforcement per tool.
  - Global hook chain for cross-cutting concerns.

Usage::

    from server.tools.base import BaseTool, ToolResult, ToolRegistry, tool

    class GreetTool(BaseTool):
        name = "greet"
        description = "Return a greeting for the given name."
        parameters = {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Whom to greet."},
            },
            "required": ["name"],
        }
        tags = ["demo"]
        category = "utility"

        async def execute(self, name: str) -> ToolResult:
            return ToolResult.ok({"greeting": f"Hello, {name}!"})

    registry = ToolRegistry()
    await registry.register(GreetTool())
    print(await registry.to_openai_tools())
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import (Any, Callable, ClassVar, Coroutine, Dict, List,
                    Optional, Set, Tuple, Type, Union)
from collections import defaultdict

# ---------------------------------------------------------------------------
# Logger — prefer loguru if available, otherwise stdlib
# ---------------------------------------------------------------------------
try:
    from loguru import logger
except ImportError:
    import logging

    logger = logging.getLogger("agent.tools")
    logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Parameter validation — optional jsonschema support
# ---------------------------------------------------------------------------
try:
    import jsonschema

    _HAS_VALIDATOR = True
except ImportError:
    _HAS_VALIDATOR = False

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ToolError(Exception):
    """Base exception for all tool-related errors."""


class ToolValidationError(ToolError):
    """Raised when incoming parameters fail JSON Schema validation."""


class ToolNotFoundError(ToolError):
    """Raised when a requested tool name is not in the registry."""


class ToolExecutionError(ToolError):
    """Wraps an unhandled exception that occurred inside ``execute``."""


class ToolTimeoutError(ToolError):
    """Raised when a tool exceeds its configured ``timeout_seconds``."""


# ---------------------------------------------------------------------------
# ToolResult
# ---------------------------------------------------------------------------


@dataclass
class ToolResult:
    """Standardised result envelope returned by every tool execution.

    Attributes:
        success: ``True`` if the tool completed without error.
        data: The primary payload (any JSON-serialisable value).
        error: Human-readable error message when ``success`` is ``False``.
        metadata: Arbitrary extra information (timing, tokens, cache hits, …).
    """

    success: bool
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Factory helpers
    # ------------------------------------------------------------------

    @classmethod
    def ok(cls, data: Any = None, **metadata: Any) -> "ToolResult":
        """Create a successful result."""
        return cls(success=True, data=data, metadata=dict(metadata))

    @classmethod
    def fail(cls, error: str, data: Any = None, **metadata: Any) -> "ToolResult":
        """Create a failed result."""
        return cls(success=False, data=data, error=error, metadata=dict(metadata))

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain dict suitable for JSON serialisation."""
        d: Dict[str, Any] = {"success": self.success, "data": self.data}
        if self.error is not None:
            d["error"] = self.error
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    def to_json(self) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    def to_string(self) -> str:
        """Return a human-readable string for LLM consumption."""
        if not self.success:
            return f"[工具执行失败] {self.error}"
        if isinstance(self.data, str):
            return self.data
        if isinstance(self.data, (list, dict)):
            return json.dumps(self.data, ensure_ascii=False, indent=2)
        return str(self.data)

    def __bool__(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# BaseTool
# ---------------------------------------------------------------------------


class BaseTool(ABC):
    """Abstract base for every agent tool.

    Subclasses **must** set at least ``name``, ``description``, and
    ``parameters``.  The ``execute`` coroutine is the only required
    override.

    Class attributes
    ----------------
    name : str
        Unique identifier used by the registry and LLM tool-selection.
    description : str
        Purpose and usage guidance — this is shown to the LLM so it can
        decide *when* to invoke the tool.
    parameters : dict
        JSON Schema (draft-7) describing the arguments accepted by
        ``execute``.  Must follow the ``{"type": "object", …}`` form.
        When subclasses set ``parameters`` as a flat dict of
        ``{param_name: schema}``, the ``type: object`` envelope is
        added automatically in the schema exporters.
    tags : list[str]
        Zero or more free-form tags for discovery / filtering.
    category : str
        Logical grouping (e.g. ``"file"``, ``"web"``, ``"knowledge"``,
        ``"data"``, ``"media"``, ``"system"``).
    version : str
        Semver-style version string.
    author : str
        Human-readable author attribution.
    require_confirmation : bool
        When ``True`` the host should prompt the user before the tool
        is invoked.  Use for destructive or side-effectful tools.
    timeout_seconds : float | None
        Maximum wall-clock duration for ``execute``.  ``None`` means
        unbounded.
    """

    # ---- Subclasses MUST override ----
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    # ---- Subclasses MAY override ----
    tags: List[str] = []
    category: str = "general"
    version: str = "0.1.0"
    author: str = ""
    require_confirmation: bool = False
    timeout_seconds: Optional[float] = None

    # ---- Lifecycle hooks (WorkBuddy / Trae style) ----

    async def before_execute(self, params: Dict[str, Any]) -> Optional[ToolResult]:
        """Hook called **before** ``execute``.

        Return a ``ToolResult`` to short-circuit execution (e.g. for
        caching or early rejection).  Return ``None`` to proceed
        normally.
        """
        _ = params
        return None

    async def after_execute(
        self, params: Dict[str, Any], result: ToolResult
    ) -> ToolResult:
        """Hook called **after** ``execute`` (and still called if execute
        raises, with a failing ``ToolResult``).

        The default implementation is a no-op pass-through.
        """
        _ = params
        return result

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Execute the tool with validated parameters.

        ``kwargs`` contains the concrete arguments extracted from the
        tool-call request, already matched to the JSON Schema declared
        in ``parameters``.  Validation happens automatically in
        :meth:`call` before this method is invoked.

        Returns a :class:`ToolResult`.
        """
        ...

    async def call(self, **kwargs: Any) -> ToolResult:
        """Public entry point: validate → before → execute → after.

        This is the method that tool consumers (LLM orchestrators)
        should invoke.  It handles:

        1. JSON-Schema validation (if ``jsonschema`` is installed).
        2. The ``before_execute`` hook (opportunity to short-circuit).
        3. ``execute`` itself, with optional timeout.
        4. The ``after_execute`` hook for post-processing / logging.
        """
        t0 = time.perf_counter()

        # --- step 1: validate --------------------------------------------
        validation_result = self._validate_params(kwargs)
        if validation_result is not None:
            validation_result.metadata["duration_ms"] = _ms(t0)
            validation_result.metadata["tool_name"] = self.name
            return validation_result

        # --- step 2: before hook -----------------------------------------
        try:
            short_circuit = await self.before_execute(kwargs)
        except Exception as exc:
            logger.exception("before_execute hook raised for tool %r", self.name)
            return ToolResult.fail(
                f"before_execute hook error: {exc}",
                metadata={"tool_name": self.name, "duration_ms": _ms(t0)},
            )
        if short_circuit is not None:
            short_circuit.metadata["duration_ms"] = _ms(t0)
            short_circuit.metadata["tool_name"] = self.name
            return short_circuit

        # --- step 3: execute (with optional timeout) ---------------------
        try:
            if self.timeout_seconds is not None:
                result = await asyncio.wait_for(
                    self.execute(**kwargs), timeout=self.timeout_seconds
                )
            else:
                result = await self.execute(**kwargs)

            # Coerce bare return values
            if not isinstance(result, ToolResult):
                result = ToolResult.ok(data=result)
        except asyncio.TimeoutError:
            result = ToolResult.fail(
                f"Tool {self.name!r} timed out after {self.timeout_seconds}s",
                metadata={"tool_name": self.name, "duration_ms": _ms(t0)},
            )
        except Exception as exc:
            logger.exception("Unhandled error in tool %r", self.name)
            result = ToolResult.fail(
                str(exc),
                metadata={"tool_name": self.name, "duration_ms": _ms(t0)},
            )

        result.metadata.setdefault("duration_ms", _ms(t0))
        result.metadata.setdefault("tool_name", self.name)

        # --- step 4: after hook ------------------------------------------
        try:
            result = await self.after_execute(kwargs, result)
        except Exception as exc:
            logger.exception("after_execute hook raised for tool %r", self.name)
            result.metadata["after_execute_error"] = str(exc)

        result.metadata.setdefault("duration_ms_total", _ms(t0))
        return result

    # ------------------------------------------------------------------
    # Schema conversion
    # ------------------------------------------------------------------

    def to_openai_schema(self) -> Dict[str, Any]:
        """Return a tool definition compatible with the OpenAI Chat
        Completions ``tools`` array (``function`` type).

        https://platform.openai.com/docs/guides/function-calling
        """
        params = self._normalise_params()
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self._clean_schema(params),
            },
        }

    def to_anthropic_schema(self) -> Dict[str, Any]:
        """Return a tool definition compatible with the Anthropic Messages
        ``tools`` array.

        https://docs.anthropic.com/en/docs/build-with-claude/tool-use
        """
        params = self._normalise_params()
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self._clean_schema(params),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Generic dictionary representation (useful for APIs / debugging)."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self._normalise_params(),
            "tags": self.tags,
            "category": self.category,
            "version": self.version,
            "author": self.author,
            "require_confirmation": self.require_confirmation,
        }

    # ------------------------------------------------------------------
    # Parameter normalisation
    # ------------------------------------------------------------------

    def _normalise_params(self) -> Dict[str, Any]:
        """Ensure ``self.parameters`` is a valid JSON Schema object.

        If the user supplied a flat ``{prop: schema}`` dict (the
        WorkBuddy style), wrap it in ``type: object`` automatically.
        If it already has a ``type`` key, return it unchanged.
        """
        p = self.parameters
        if not isinstance(p, dict):
            return {"type": "object", "properties": {}, "required": []}

        # Already looks like a full JSON Schema (has "type" or "properties")
        if "type" in p or "properties" in p or "$schema" in p:
            return p

        # Flat {param_name: schema} style — wrap it
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for key, val in p.items():
            if not isinstance(val, dict):
                val = {"type": "string", "description": str(val)}
            properties[key] = val
            # If no explicit "optional": True marker, treat as required
            if not val.pop("optional", False):
                required.append(key)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_params(self, params: Dict[str, Any]) -> Optional[ToolResult]:
        """Validate *params* against ``self.parameters`` (JSON Schema).

        Returns ``None`` when valid or when ``jsonschema`` is
        unavailable, otherwise a failing ``ToolResult``.
        """
        if not _HAS_VALIDATOR:
            return None  # best-effort — skip validation silently

        schema = self._normalise_params()
        try:
            jsonschema.validate(params, schema)
        except jsonschema.ValidationError as exc:
            return ToolResult.fail(
                f"Parameter validation failed for tool {self.name!r}: {exc.message}",
                data={
                    "path": list(exc.absolute_path),
                    "schema_path": list(exc.absolute_schema_path),
                },
                tool_name=self.name,
            )
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _clean_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
        """Strip keys that are not recognised JSON Schema spec keywords
        by OpenAI / Anthropic (e.g. internal metadata fields).  Returns
        a shallow-cleaned copy; recurses into ``properties`` and
        ``items``.
        """
        allowed = {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "description",
            "default",
            "examples",
            "enum",
            "const",
            "oneOf",
            "anyOf",
            "allOf",
            "not",
            "if",
            "then",
            "else",
            "items",
            "minItems",
            "maxItems",
            "uniqueItems",
            "minLength",
            "maxLength",
            "pattern",
            "minimum",
            "maximum",
            "exclusiveMinimum",
            "exclusiveMaximum",
            "multipleOf",
            "format",
            "title",
            "definitions",
            "$defs",
            "$ref",
            "$schema",
        }
        cleaned: Dict[str, Any] = {}
        for k, v in schema.items():
            if k in allowed:
                cleaned[k] = v

        if "properties" in cleaned and isinstance(cleaned["properties"], dict):
            cleaned["properties"] = {
                pk: BaseTool._clean_schema(pv) if isinstance(pv, dict) else pv
                for pk, pv in cleaned["properties"].items()
            }
        if "items" in cleaned and isinstance(cleaned["items"], dict):
            cleaned["items"] = BaseTool._clean_schema(cleaned["items"])

        return cleaned

    def __repr__(self) -> str:
        return f"<{type(self).__name__} name={self.name!r}>"


# ---------------------------------------------------------------------------
# Global hook type
# ---------------------------------------------------------------------------

GlobalHook = Callable[
    ["BaseTool", Dict[str, Any], Callable[..., Coroutine[Any, Any, ToolResult]]],
    Coroutine[Any, Any, ToolResult],
]
"""Signature for a global middleware hook.

    async def my_hook(
        tool: BaseTool,
        params: Dict[str, Any],
        next_call: Callable[..., Coroutine],
    ) -> ToolResult:
        ...
"""


# ---------------------------------------------------------------------------
# ToolRegistry — singleton
# ---------------------------------------------------------------------------


class ToolRegistry:
    """Thread-safe singleton registry that holds all active tools.

    Usage::

        reg = ToolRegistry()
        await reg.register(MyTool())
        tool = await reg.get_tool("my_tool")
        result = await tool.call(arg=42)

        # Export for LLM providers
        openai_tools = await reg.to_openai_tools()
        anthropic_tools = await reg.to_anthropic_tools()

        # Filtering
        for t in await reg.list_tools(category="file"):
            print(t.name)
    """

    _instance: ClassVar[Optional["ToolRegistry"]] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __new__(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._tools: Dict[str, BaseTool] = {}
            cls._instance._tags_index: Dict[str, Set[str]] = defaultdict(set)
            cls._instance._category_index: Dict[str, Set[str]] = defaultdict(set)
            cls._instance._call_counts: Dict[str, int] = defaultdict(int)
            cls._instance._error_counts: Dict[str, int] = defaultdict(int)
            cls._instance._global_hooks: List[GlobalHook] = []
        return cls._instance

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register(self, tool: BaseTool) -> None:
        """Register *tool* in the registry.

        Raises ``ValueError`` if a tool with the same name is already
        registered.
        """
        async with self._lock:
            if tool.name in self._tools:
                raise ValueError(
                    f"Tool {tool.name!r} is already registered. "
                    f"Unregister it first or use a unique name."
                )
            self._tools[tool.name] = tool

            for tag in tool.tags:
                self._tags_index[tag].add(tool.name)

            cat = tool.category or "__uncategorized__"
            self._category_index[cat].add(tool.name)

            logger.info(
                "Tool registered: {name} (category={cat}, tags={tags})",
                name=tool.name,
                cat=cat,
                tags=tool.tags,
            )

    async def unregister(self, name: str) -> Optional[BaseTool]:
        """Remove *name* from the registry.

        Returns the removed tool or ``None`` if it was not found.
        """
        async with self._lock:
            tool = self._tools.pop(name, None)
            if tool is None:
                return None

            self._call_counts.pop(name, None)
            self._error_counts.pop(name, None)

            for tag in tool.tags:
                names = self._tags_index.get(tag)
                if names:
                    names.discard(name)
                    if not names:
                        del self._tags_index[tag]

            cat = tool.category or "__uncategorized__"
            names = self._category_index.get(cat)
            if names:
                names.discard(name)
                if not names:
                    del self._category_index[cat]

            logger.info("Tool unregistered: {name}", name=name)
            return tool

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    async def get_tool(self, name: str) -> BaseTool:
        """Return the registered tool with *name*.

        Raises ``ToolNotFoundError`` if absent.
        """
        async with self._lock:
            try:
                return self._tools[name]
            except KeyError:
                raise ToolNotFoundError(
                    f"Tool {name!r} not found. "
                    f"Registered tools: {sorted(self._tools)}"
                )

    async def get_tool_or_none(self, name: str) -> Optional[BaseTool]:
        """Return the registered tool with *name*, or ``None``."""
        async with self._lock:
            return self._tools.get(name)

    async def has_tool(self, name: str) -> bool:
        """Return ``True`` if *name* is registered."""
        async with self._lock:
            return name in self._tools

    # ------------------------------------------------------------------
    # Listing & filtering
    # ------------------------------------------------------------------

    async def list_tools(
        self,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
        exclude_tags: Optional[List[str]] = None,
        require_confirmation: Optional[bool] = None,
    ) -> List[BaseTool]:
        """Return tools matching all given criteria.

        Parameters
        ----------
        tags:
            If provided, only tools that have **all** of these tags are
            returned.
        category:
            If provided, only tools in this category are returned.
        exclude_tags:
            If provided, tools that have **any** of these tags are
            excluded.
        require_confirmation:
            If provided, filter by the ``require_confirmation`` flag.
        """
        async with self._lock:
            result = list(self._tools.values())

        if tags:
            tag_set = set(tags)
            result = [t for t in result if tag_set.issubset(set(t.tags))]

        if exclude_tags:
            exclude_set = set(exclude_tags)
            result = [t for t in result if not exclude_set.intersection(set(t.tags))]

        if category is not None:
            result = [t for t in result if t.category == category]

        if require_confirmation is not None:
            result = [t for t in result if t.require_confirmation == require_confirmation]

        return result

    async def list_tool_summaries(
        self,
        tags: Optional[List[str]] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Like :meth:`list_tools` but returns lightweight dicts with
        ``name``, ``description``, ``tags``, and ``category`` only.
        """
        tools = await self.list_tools(tags=tags, category=category)
        return [
            {
                "name": t.name,
                "description": t.description,
                "tags": t.tags,
                "category": t.category,
                "require_confirmation": t.require_confirmation,
            }
            for t in tools
        ]

    # ------------------------------------------------------------------
    # Tag & category helpers
    # ------------------------------------------------------------------

    async def all_tags(self) -> Set[str]:
        """Return every tag used by at least one tool."""
        async with self._lock:
            return set(self._tags_index.keys())

    async def all_categories(self) -> Set[str]:
        """Return every category used by at least one tool."""
        async with self._lock:
            cats = set(self._category_index.keys())
            cats.discard("__uncategorized__")
            return cats

    async def get_tools_by_tag(self, tag: str) -> List[BaseTool]:
        """Return all tools that have *tag*."""
        async with self._lock:
            names = self._tags_index.get(tag, set())
            return [self._tools[n] for n in names if n in self._tools]

    async def get_tools_by_category(self, category: str) -> List[BaseTool]:
        """Return all tools that belong to *category*."""
        async with self._lock:
            names = self._category_index.get(category, set())
            return [self._tools[n] for n in names if n in self._tools]

    # ------------------------------------------------------------------
    # Schema export (LLM providers)
    # ------------------------------------------------------------------

    async def to_openai_tools(
        self, enabled: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Return the OpenAI ``tools`` array.

        If *enabled* is provided, only those tool names are included.
        """
        if enabled is not None:
            tools = [await self.get_tool(n) for n in enabled if await self.has_tool(n)]
        else:
            async with self._lock:
                tools = list(self._tools.values())
        return [t.to_openai_schema() for t in tools]

    async def to_anthropic_tools(
        self, enabled: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """Return the Anthropic ``tools`` array.

        If *enabled* is provided, only those tool names are included.
        """
        if enabled is not None:
            tools = [await self.get_tool(n) for n in enabled if await self.has_tool(n)]
        else:
            async with self._lock:
                tools = list(self._tools.values())
        return [t.to_anthropic_schema() for t in tools]

    # ------------------------------------------------------------------
    # Execution & stats
    # ------------------------------------------------------------------

    async def call(self, name: str, **kwargs: Any) -> ToolResult:
        """Look up *name* and invoke ``tool.call(**kwargs)``.

        This is the recommended single-entry-point for orchestrators.
        It tracks call / error counts on the registry and runs any
        registered global hooks.
        """
        tool = await self.get_tool(name)

        async with self._lock:
            self._call_counts[name] += 1

        # Build the "next" callable that runs the tool itself
        async def _run_tool(**kw: Any) -> ToolResult:
            return await tool.call(**kw)

        # Wrap with global hooks (outermost → innermost → tool)
        next_call: Callable[..., Coroutine[Any, Any, ToolResult]] = _run_tool
        for hook in reversed(self._global_hooks):
            current = next_call
            bound = functools.partial(hook, tool, kwargs)
            next_call = lambda _bound=bound, _current=current: _bound(_current)  # type: ignore[misc]

        result = await next_call(**kwargs)

        if not result.success:
            async with self._lock:
                self._error_counts[name] += 1

        return result

    async def get_stats(self) -> Dict[str, Any]:
        """Return registry statistics."""
        async with self._lock:
            by_category: Dict[str, int] = defaultdict(int)
            for t in self._tools.values():
                by_category[t.category or "__uncategorized__"] += 1

            return {
                "total_tools": len(self._tools),
                "call_counts": dict(self._call_counts),
                "error_counts": dict(self._error_counts),
                "by_category": dict(by_category),
            }

    # ------------------------------------------------------------------
    # Global hooks  (Trae-style middleware chain)
    # ------------------------------------------------------------------

    def add_global_hook(self, hook: GlobalHook) -> None:
        """Register an async callable invoked around every tool execution.

        The *hook* signature::

            async def hook(
                tool: BaseTool,
                params: Dict[str, Any],
                next_call: Callable[..., Coroutine],
            ) -> ToolResult:
                ...

        *next_call* is an awaitable that, when called, runs the rest of
        the pipeline (remaining hooks + the tool's own before/execute/after).
        """
        self._global_hooks.append(hook)

    def remove_global_hook(self, hook: GlobalHook) -> None:
        """Remove a previously added global hook."""
        try:
            self._global_hooks.remove(hook)
        except ValueError:
            pass

    def clear_global_hooks(self) -> None:
        """Remove all global hooks."""
        self._global_hooks.clear()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @property
    def count(self) -> int:
        """Number of registered tools."""
        return len(self._tools)

    # ------------------------------------------------------------------
    # Reset (mainly for tests)
    # ------------------------------------------------------------------

    @classmethod
    async def reset(cls) -> None:
        """Clear the singleton entirely.  Useful in test teardown."""
        async with cls._lock:
            cls._instance = None


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

registry = ToolRegistry()
"""Pre-built singleton instance for convenience."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms(t0: float) -> float:
    """Elapsed milliseconds since *t0* (``time.perf_counter``)."""
    return round((time.perf_counter() - t0) * 1000, 2)


# ---------------------------------------------------------------------------
# ``@tool`` decorator
# ---------------------------------------------------------------------------

_type_map: Dict[Type[Any], str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}


def _schema_from_func(fn: Callable[..., Any]) -> Dict[str, Any]:
    """Build a minimal JSON Schema from a function's type annotations."""
    sig = inspect.signature(fn)
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for pname, param in sig.parameters.items():
        if pname in ("self", "cls"):
            continue

        ann = param.annotation
        if ann is inspect.Parameter.empty:
            json_type = "string"
        else:
            # Handle Optional[X] / Union[X, None]
            origin = getattr(ann, "__origin__", None)
            if origin is Union:
                args = [a for a in getattr(ann, "__args__", ()) if a is not type(None)]
                if len(args) == 1:
                    ann = args[0]
                else:
                    ann = args[0] if args else str
            json_type = _type_map.get(ann, "string")

        prop: Dict[str, Any] = {"type": json_type}

        if param.default is not inspect.Parameter.empty:
            prop["default"] = param.default
        else:
            required.append(pname)

        properties[pname] = prop

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


def tool(
    *,
    name: Optional[str] = None,
    description: Optional[str] = None,
    parameters: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    version: str = "0.1.0",
    author: str = "",
    require_confirmation: bool = False,
    timeout_seconds: Optional[float] = None,
):
    """Decorator that turns an async function into a :class:`BaseTool`.

    The decorated function's signature is introspected via type hints
    to build a basic JSON Schema when ``parameters`` is not supplied.

    The decorated function may return a :class:`ToolResult` directly,
    or a bare value that will be wrapped in ``ToolResult.ok(...)``.

    Example::

        @tool(name="add", description="Add two numbers", category="math")
        async def add(a: int, b: int) -> ToolResult:
            return ToolResult.ok(a + b)

        await registry.register(add)  # add is already a BaseTool instance.
    """

    def decorator(fn: Callable[..., Any]) -> BaseTool:
        par_schema = parameters
        if par_schema is None:
            par_schema = _schema_from_func(fn)

        tool_name = name or fn.__name__

        class _DecoratedTool(BaseTool):
            pass

        _DecoratedTool.name = tool_name
        _DecoratedTool.description = description or fn.__doc__ or ""
        _DecoratedTool.parameters = par_schema
        _DecoratedTool.tags = tags or []
        _DecoratedTool.category = category or "general"
        _DecoratedTool.version = version
        _DecoratedTool.author = author
        _DecoratedTool.require_confirmation = require_confirmation
        _DecoratedTool.timeout_seconds = timeout_seconds

        async def _execute(self: BaseTool, **kwargs: Any) -> ToolResult:
            result = await fn(**kwargs)
            if isinstance(result, ToolResult):
                return result
            return ToolResult.ok(data=result)

        _DecoratedTool.execute = _execute
        _DecoratedTool.__name__ = tool_name  # type: ignore[attr-defined]
        _DecoratedTool.__qualname__ = tool_name  # type: ignore[attr-defined]

        return _DecoratedTool()

    return decorator
