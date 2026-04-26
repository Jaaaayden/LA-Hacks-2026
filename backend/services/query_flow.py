from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from backend.kitscout.db import queries, shopping_lists
from backend.kitscout.schemas import Query, ShoppingList
from backend.services.gen_followup import gen_followup
from backend.services.gen_list import gen_list
from backend.services.intent_parser import INTENT_SKELETON, parse_intent

DEFAULT_INTENT_MODEL = "claude-sonnet-4-5"
DEFAULT_LIST_MODEL = "claude-sonnet-4-5"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid Mongo ObjectId: {value}") from exc


def _serialize_id(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


async def create_query_session(
    user_text: str,
    *,
    skeleton: dict[str, Any] | None = None,
    include_hobby_other_flags: bool = True,
    intent_model: str = DEFAULT_INTENT_MODEL,
    followup_model: str = DEFAULT_INTENT_MODEL,
) -> dict[str, Any]:
    """Parse an initial prompt, store it, and persist any follow-up questions."""
    base_skeleton = dict(skeleton or INTENT_SKELETON)
    parsed_intent = parse_intent(user_text, base_skeleton, model=intent_model)

    merged_intent: dict[str, Any] = {}
    followup = gen_followup(
        parsed_intent,
        include_hobby_other_flags=include_hobby_other_flags,
        model=followup_model,
        merged_intent_out=merged_intent,
    )
    final_intent = merged_intent or parsed_intent
    questions = followup.get("questions") or []
    now = _now()

    doc = Query(
        raw_messages=[user_text],
        parsed_intent=final_intent,
        followup_questions=questions,
        status="followups_ready",
        created_at=now,
        updated_at=now,
    )
    result = await queries.insert_one(doc.model_dump())

    return {
        "query_id": str(result.inserted_id),
        "parsed_intent": final_intent,
        "followup_questions": questions,
        "status": doc.status,
    }


async def complete_query_session(
    query_id: str,
    followup_text: str,
    *,
    intent_model: str = DEFAULT_INTENT_MODEL,
    list_model: str = DEFAULT_LIST_MODEL,
) -> dict[str, Any]:
    """Parse follow-up text, store completed intent, then persist a shopping list."""
    oid = _object_id(query_id)
    existing = await queries.find_one({"_id": oid})
    if existing is None:
        raise ValueError(f"Query not found: {query_id}")

    completed_intent = parse_intent(
        followup_text,
        existing["parsed_intent"],
        model=intent_model,
    )
    shopping_list_payload = gen_list(completed_intent, model=list_model)
    now = _now()

    shopping_list_doc = ShoppingList(
        query_id=query_id,
        hobby=shopping_list_payload["hobby"],
        budget_usd=shopping_list_payload.get("budget_usd"),
        items=shopping_list_payload["items"],
        source_model=list_model,
        created_at=now,
    )
    shopping_result = await shopping_lists.insert_one(shopping_list_doc.model_dump())
    shopping_list_id = str(shopping_result.inserted_id)

    await queries.update_one(
        {"_id": oid},
        {
            "$set": {
                "parsed_intent": completed_intent,
                "status": "shopping_list_created",
                "shopping_list_id": shopping_list_id,
                "updated_at": now,
            },
            "$push": {"raw_messages": followup_text},
        },
    )

    return {
        "query_id": query_id,
        "shopping_list_id": shopping_list_id,
        "parsed_intent": completed_intent,
        "shopping_list": shopping_list_doc.model_dump(),
    }


async def get_query_session(query_id: str) -> dict[str, Any] | None:
    doc = await queries.find_one({"_id": _object_id(query_id)})
    return _serialize_id(doc) if doc else None


async def get_shopping_list(shopping_list_id: str) -> dict[str, Any] | None:
    doc = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    return _serialize_id(doc) if doc else None


async def update_shopping_list(
    shopping_list_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Persist frontend edits to an existing shopping list and mark its query edited."""
    oid = _object_id(shopping_list_id)
    existing = await shopping_lists.find_one({"_id": oid})
    if existing is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    merged = {**existing, **updates}
    merged.pop("_id", None)
    validated = ShoppingList(**merged)
    replacement = validated.model_dump()

    await shopping_lists.update_one({"_id": oid}, {"$set": replacement})
    query_oid = _object_id(validated.query_id)
    await queries.update_one(
        {"_id": query_oid},
        {
            "$set": {
                "status": "shopping_list_edited",
                "updated_at": _now(),
            }
        },
    )

    return {"_id": shopping_list_id, **replacement}
