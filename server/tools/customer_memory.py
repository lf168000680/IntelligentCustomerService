"""
CustomerMemoryTool -- Store and retrieve customer-specific information (like a CRM).

Uses the UserProfile ORM model for persistence.  Receives a db_factory
(async_sessionmaker) via dependency injection so the caller controls
transaction boundaries.

Memory categories:
    - preferences  ->  UserProfile.preferences (JSON dict)
    - purchases    ->  UserProfile.order_count / total_spent
    - interactions ->  structured lines in UserProfile.notes
    - notes        ->  UserProfile.notes (freeform text)

Allowed operations (routed through ``execute(action=...)``):
    remember, recall, forget, list_customers, tag_customer
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from .base import BaseTool, ToolResult
from ..db.models import UserProfile


# ================================================================
#  Helpers
# ================================================================

_PREFERENCE_KEYS = {"style", "size", "color", "brand", "material", "fit", "budget"}
_PURCHASE_KEYS    = {"order_count", "total_spent", "last_purchase_date"}
_INTERACTION_KEYS = {"last_contact", "sentiment", "sentiment_history"}


def _normalise_category(key: str) -> str:
    """Guess the memory category from the key name."""
    if key in _PREFERENCE_KEYS:
        return "preferences"
    if key in _PURCHASE_KEYS:
        return "purchases"
    if key in _INTERACTION_KEYS:
        return "interactions"
    return "notes"


def _require(params: dict, key: str) -> Any:
    val = params.get(key)
    if val is None:
        raise ValueError(f"Missing required parameter: {key}")
    return val


def _append_line(base: str, line: str) -> str:
    return (base.rstrip() + "\n" + line).strip()


def _remove_line(notes: str, key: str) -> str:
    """Remove all lines in notes that reference *key*."""
    kept = []
    for line in notes.splitlines():
        stripped = line.strip()
        if f"{key}=" in stripped:
            continue
        kept.append(stripped)
    return "\n".join(kept).strip()


def _find_in_notes(notes: str, key: str) -> Optional[str]:
    """Search structured notes lines for a key."""
    for line in notes.splitlines():
        line = line.strip()
        if not line or "=" not in line:
            continue
        # lines look like: [category] key=value (timestamp)
        # extract payload between first ']' and '(' if present
        if "]" in line:
            rest = line[line.index("]") + 1:].strip()
        else:
            rest = line
        if "=" in rest:
            k, _, v = rest.partition("=")
            if k.strip() == key:
                v = v.strip()
                if "(" in v:
                    v = v[: v.rindex("(")].strip()
                return v
    return None


def _serialise_profile(profile: UserProfile, brief: bool = False) -> dict:
    """Convert a UserProfile row into a dict suitable for LLM consumption."""
    data: Dict[str, Any] = {
        "user_id": profile.user_id,
        "platform": profile.platform,
        "user_name": profile.user_name,
    }

    if brief:
        data["tags"] = profile.tags or []
        data["order_count"] = profile.order_count
        data["total_spent"] = profile.total_spent
        if profile.preferences:
            data["preferences"] = profile.preferences
        return data

    data["tags"] = profile.tags or []
    data["preferences"] = profile.preferences or {}
    data["order_count"] = profile.order_count
    data["total_spent"] = profile.total_spent
    data["notes"] = profile.notes or ""
    data["last_seen"] = profile.last_seen.isoformat() if profile.last_seen else None
    data["created_at"] = profile.created_at.isoformat() if profile.created_at else None
    data["updated_at"] = profile.updated_at.isoformat() if profile.updated_at else None
    return data


# ================================================================
#  Tool
# ================================================================

class CustomerMemoryTool(BaseTool):
    """
    Store and recall per-customer facts (preferences, purchases,
    interaction history, freeform notes).

    Usage via ``execute``::

        # store a preference
        await tool.execute(action="remember", user_id="tb_123",
                           key="style", value="法式复古风格",
                           platform="taobao")

        # recall all facts about a customer
        await tool.execute(action="recall", user_id="tb_123")

        # recall specific fact
        await tool.execute(action="recall", user_id="tb_123", key="style")

        # delete a fact
        await tool.execute(action="forget", user_id="tb_123", key="style")

        # list customers by tag
        await tool.execute(action="list_customers", tag="VIP")

        # add tags to customer
        await tool.execute(action="tag_customer", user_id="tb_123",
                           tags=["VIP", "老客户"])
    """

    name: str = "customer_memory"
    description: str = (
        "Manage customer information (CRM). "
        "Use 'remember' to save a fact (preferences, purchases, interactions, notes), "
        "'recall' to retrieve customer facts (by user_id or user_id+key), "
        "'forget' to delete a specific fact, "
        "'list_customers' to find customers by a tag, "
        "'tag_customer' to assign tags to a customer profile."
    )
    category: str = "data"

    parameters: dict = {
        "action": {
            "type": "string",
            "description": "Operation to perform.",
            "enum": ["remember", "recall", "forget", "list_customers", "tag_customer"],
        },
        "user_id": {
            "type": "string",
            "description": "Platform user ID (e.g. taobao buyer ID / douyin user ID).",
        },
        "platform": {
            "type": "string",
            "description": "Platform name (taobao / douyin). Default: taobao.",
        },
        "key": {
            "type": "string",
            "description": (
                "Fact key name.  Examples: style, size, color (preferences); "
                "order_count, total_spent (purchases); "
                "last_contact, sentiment (interactions); "
                "or any freeform key (notes)."
            ),
        },
        "value": {
            "type": "string",
            "description": "Fact value (used by 'remember').",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of tags to add (used by 'tag_customer').",
        },
        "tag": {
            "type": "string",
            "description": "Single tag to search for (used by 'list_customers').",
        },
    }

    def __init__(self, db_factory: async_sessionmaker, platform: str = "taobao"):
        """
        Args:
            db_factory: An ``async_sessionmaker``.  Calling
                ``async with db_factory() as session:`` yields an
                AsyncSession that auto-commits on exit.
            platform: Default platform when not supplied per-call.
        """
        super().__init__()
        self._db_factory = db_factory
        self._default_platform = platform

    # ----------------------------------------------------------
    #  Public API  (also usable directly by Python callers)
    # ----------------------------------------------------------

    async def remember(
        self,
        user_id: str,
        key: str,
        value: Any,
        platform: Optional[str] = None,
    ) -> ToolResult:
        """Store a fact about a customer.  Category is inferred from *key*."""
        return await self._action_remember({
            "user_id": user_id,
            "key": key,
            "value": value,
            "platform": platform or self._default_platform,
        })

    async def recall(
        self,
        user_id: str,
        key: Optional[str] = None,
        platform: Optional[str] = None,
    ) -> ToolResult:
        """Retrieve facts about a customer (all or one specific key)."""
        return await self._action_recall({
            "user_id": user_id,
            "key": key or None,
            "platform": platform or self._default_platform,
        })

    async def forget(
        self,
        user_id: str,
        key: str,
        platform: Optional[str] = None,
    ) -> ToolResult:
        """Delete a fact about a customer."""
        return await self._action_forget({
            "user_id": user_id,
            "key": key,
            "platform": platform or self._default_platform,
        })

    async def list_customers(self, tag: str) -> ToolResult:
        """List customers that have a given tag."""
        return await self._action_list_customers({"tag": tag})

    async def tag_customer(
        self,
        user_id: str,
        tags: List[str],
        platform: Optional[str] = None,
    ) -> ToolResult:
        """Add tags to a customer profile."""
        return await self._action_tag_customer({
            "user_id": user_id,
            "tags": tags,
            "platform": platform or self._default_platform,
        })

    # ----------------------------------------------------------
    #  execute() entrypoint for LLM tool-use
    # ----------------------------------------------------------

    async def execute(self, **kwargs) -> ToolResult:
        """Route to the correct sub-operation based on ``action``."""
        action = (kwargs.get("action") or "").strip().lower()
        if not action:
            return ToolResult(success=False, error="Missing required parameter: action")

        method = getattr(self, f"_action_{action}", None)
        if method is None:
            return ToolResult(
                success=False,
                error=f"Unknown action '{action}'. "
                      f"Valid: remember, recall, forget, list_customers, tag_customer",
            )
        try:
            return await method(kwargs)
        except Exception as exc:
            logger.exception(f"customer_memory.{action} failed")
            return ToolResult(success=False, error=str(exc))

    # ----------------------------------------------------------
    #  Action handlers
    # ----------------------------------------------------------

    async def _action_remember(self, params: dict) -> ToolResult:
        user_id   = _require(params, "user_id")
        key       = _require(params, "key")
        value     = params.get("value")
        platform  = params.get("platform", self._default_platform)

        if value is None:
            return ToolResult(success=False, error="Missing required parameter: value")

        category = _normalise_category(key)
        now = datetime.now()

        async with self._db_factory() as db:
            profile = await self._get_or_create_profile(db, platform, user_id)

            if category == "preferences":
                prefs = profile.preferences or {}
                prefs[key] = value
                profile.preferences = prefs

            elif category == "purchases":
                if key == "order_count":
                    profile.order_count = int(value)
                elif key == "total_spent":
                    profile.total_spent = float(value)
                else:
                    profile.notes = _append_line(
                        profile.notes or "",
                        f"[purchases] {key}={value} ({now.isoformat()})",
                    )

            elif category == "interactions":
                profile.notes = _append_line(
                    profile.notes or "",
                    f"[interactions] {key}={value} ({now.isoformat()})",
                )
                profile.last_seen = now

            else:  # notes
                profile.notes = _append_line(
                    profile.notes or "",
                    f"[note] {key}: {value} ({now.isoformat()})",
                )

            await db.commit()

        logger.info(f"customer_memory.remember user={user_id} key={key} category={category}")
        return ToolResult(
            success=True,
            data={
                "user_id": user_id,
                "key": key,
                "value": value,
                "category": category,
                "stored": True,
            },
        )

    async def _action_recall(self, params: dict) -> ToolResult:
        user_id  = _require(params, "user_id")
        key      = params.get("key")
        platform = params.get("platform", self._default_platform)

        async with self._db_factory() as db:
            profile = await self._get_profile(db, platform, user_id)
            if profile is None:
                return ToolResult(
                    success=True,
                    data={
                        "user_id": user_id,
                        "platform": platform,
                        "found": False,
                        "message": "No profile yet -- this appears to be a new customer.",
                    },
                )

            if key:
                fact = self._extract_key(profile, key)
                return ToolResult(
                    success=True,
                    data={
                        "user_id": user_id,
                        "platform": platform,
                        "found": fact is not None,
                        "key": key,
                        "value": fact,
                    },
                )
            else:
                # Return full profile for LLM consumption
                return ToolResult(success=True, data=_serialise_profile(profile))

    async def _action_forget(self, params: dict) -> ToolResult:
        user_id  = _require(params, "user_id")
        key      = _require(params, "key")
        platform = params.get("platform", self._default_platform)
        category = _normalise_category(key)

        async with self._db_factory() as db:
            profile = await self._get_profile(db, platform, user_id)
            if profile is None:
                return ToolResult(
                    success=True,
                    data={
                        "user_id": user_id,
                        "key": key,
                        "forgotten": False,
                        "message": "Profile not found.",
                    },
                )

            removed = None

            if category == "preferences":
                prefs = profile.preferences or {}
                removed = prefs.pop(key, None)
                profile.preferences = prefs

            elif category == "purchases":
                if key == "order_count":
                    removed = profile.order_count
                    profile.order_count = 0
                elif key == "total_spent":
                    removed = profile.total_spent
                    profile.total_spent = 0.0
                else:
                    removed = True
                    profile.notes = _remove_line(profile.notes or "", key)

            elif category == "interactions":
                removed = True
                profile.notes = _remove_line(profile.notes or "", key)

            else:  # notes
                removed = True
                profile.notes = _remove_line(profile.notes or "", key)

            await db.commit()

        return ToolResult(
            success=True,
            data={
                "user_id": user_id,
                "key": key,
                "forgotten": removed is not None,
            },
        )

    async def _action_list_customers(self, params: dict) -> ToolResult:
        tag = _require(params, "tag")

        async with self._db_factory() as db:
            result = await db.execute(
                select(UserProfile)
                .where(UserProfile.tags.contains([tag]))
                .order_by(UserProfile.updated_at.desc())
                .limit(50)
            )
            profiles = result.scalars().all()

        customers = [_serialise_profile(p, brief=True) for p in profiles]
        return ToolResult(
            success=True,
            data={
                "tag": tag,
                "count": len(customers),
                "customers": customers,
            },
        )

    async def _action_tag_customer(self, params: dict) -> ToolResult:
        user_id  = _require(params, "user_id")
        tags     = _require(params, "tags")
        platform = params.get("platform", self._default_platform)

        if not isinstance(tags, list):
            return ToolResult(success=False, error="tags must be a list of strings")

        async with self._db_factory() as db:
            profile = await self._get_or_create_profile(db, platform, user_id)

            existing = set(profile.tags or [])
            before = len(existing)
            existing.update(tags)
            profile.tags = sorted(existing)
            added = len(existing) - before

            await db.commit()

        return ToolResult(
            success=True,
            data={
                "user_id": user_id,
                "platform": platform,
                "tags": profile.tags,
                "added": added,
            },
        )

    # ----------------------------------------------------------
    #  DB helpers
    # ----------------------------------------------------------

    @staticmethod
    async def _get_profile(db, platform: str, user_id: str) -> Optional[UserProfile]:
        result = await db.execute(
            select(UserProfile).where(
                UserProfile.platform == platform,
                UserProfile.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def _get_or_create_profile(db, platform: str, user_id: str) -> UserProfile:
        profile = await CustomerMemoryTool._get_profile(db, platform, user_id)
        if profile is None:
            profile = UserProfile(
                id=str(uuid.uuid4()),
                platform=platform,
                user_id=user_id,
            )
            db.add(profile)
            await db.flush()
        return profile

    @staticmethod
    def _extract_key(profile: UserProfile, key: str) -> Any:
        """Pull a single fact out of the profile."""
        category = _normalise_category(key)

        if category == "preferences":
            prefs = profile.preferences or {}
            return prefs.get(key)

        if category == "purchases":
            if key == "order_count":
                return profile.order_count
            if key == "total_spent":
                return profile.total_spent
            return _find_in_notes(profile.notes or "", key)

        if category == "interactions":
            return _find_in_notes(profile.notes or "", key)

        # notes or unknown
        return _find_in_notes(profile.notes or "", key)
