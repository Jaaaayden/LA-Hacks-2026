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
DEFAULT_MAX_FOLLOWUP_QUESTIONS = 18


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


def _question_count(doc: dict[str, Any]) -> int:
    return int(doc.get("questions_asked_count") or len(doc.get("followup_questions") or []))


def _max_followups(doc: dict[str, Any]) -> int:
    return int(doc.get("max_followup_questions") or DEFAULT_MAX_FOLLOWUP_QUESTIONS)


def _question_history(doc: dict[str, Any]) -> list[str]:
    history = doc.get("followup_question_history")
    if isinstance(history, list):
        return [str(question) for question in history]
    return [str(question) for question in doc.get("followup_questions") or []]


async def _create_shopping_list(
    *,
    query_id: str,
    query_oid: ObjectId,
    completed_intent: dict[str, Any],
    followup_text: str | None,
    questions_asked_count: int,
    max_followup_questions: int,
    list_model: str,
) -> dict[str, Any]:
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

    update: dict[str, Any] = {
        "$set": {
            "parsed_intent": completed_intent,
            "status": "shopping_list_created",
            "shopping_list_id": shopping_list_id,
            "followup_questions": [],
            "questions_asked_count": questions_asked_count,
            "max_followup_questions": max_followup_questions,
            "updated_at": now,
        }
    }
    if followup_text is not None:
        update["$push"] = {"raw_messages": followup_text}

    await queries.update_one({"_id": query_oid}, update)

    return {
        "query_id": query_id,
        "shopping_list_id": shopping_list_id,
        "parsed_intent": completed_intent,
        "shopping_list": shopping_list_doc.model_dump(),
        "status": "shopping_list_created",
        "followup_questions": [],
        "questions_asked_count": questions_asked_count,
        "max_followup_questions": max_followup_questions,
        "done": True,
    }


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
    max_followup_questions = DEFAULT_MAX_FOLLOWUP_QUESTIONS
    questions = (followup.get("questions") or [])[:max_followup_questions]
    now = _now()

    doc = Query(
        raw_messages=[user_text],
        parsed_intent=final_intent,
        followup_questions=questions,
        followup_question_history=questions,
        questions_asked_count=len(questions),
        max_followup_questions=max_followup_questions,
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
        "questions_asked_count": doc.questions_asked_count,
        "max_followup_questions": doc.max_followup_questions,
        "done": False,
    }


async def complete_query_session(
    query_id: str,
    followup_text: str,
    *,
    intent_model: str = DEFAULT_INTENT_MODEL,
    list_model: str = DEFAULT_LIST_MODEL,
) -> dict[str, Any]:
    """Parse a follow-up turn, then ask more questions or persist a shopping list."""
    oid = _object_id(query_id)
    existing = await queries.find_one({"_id": oid})
    if existing is None:
        raise ValueError(f"Query not found: {query_id}")

    completed_intent = parse_intent(
        followup_text,
        existing["parsed_intent"],
        model=intent_model,
    )
    questions_asked_count = _question_count(existing)
    max_followup_questions = _max_followups(existing)
    question_history = _question_history(existing)
    # Build the conversation transcript: every prior user message plus the
    # answer that just arrived. Lets the followup generator see what's been
    # discussed and skip topics the user already addressed.
    prior_messages = list(existing.get("raw_messages") or [])
    prior_messages.append(followup_text)

    if questions_asked_count >= max_followup_questions:
        return await _create_shopping_list(
            query_id=query_id,
            query_oid=oid,
            completed_intent=completed_intent,
            followup_text=followup_text,
            questions_asked_count=questions_asked_count,
            max_followup_questions=max_followup_questions,
            list_model=list_model,
        )

    followup = gen_followup(
        completed_intent,
        include_hobby_other_flags=False,
        model=intent_model,
        previous_questions=question_history,
        prior_user_messages=prior_messages,
    )
    next_questions = followup.get("questions") or []
    remaining_slots = max_followup_questions - questions_asked_count
    next_questions = next_questions[:remaining_slots]
    next_questions_count = questions_asked_count + len(next_questions)
    now = _now()

    if next_questions:
        next_question_history = [*question_history, *next_questions]
        await queries.update_one(
            {"_id": oid},
            {
                "$set": {
                    "parsed_intent": completed_intent,
                    "followup_questions": next_questions,
                    "followup_question_history": next_question_history,
                    "status": "followups_ready",
                    "questions_asked_count": next_questions_count,
                    "max_followup_questions": max_followup_questions,
                    "updated_at": now,
                },
                "$push": {"raw_messages": followup_text},
            },
        )

        return {
            "query_id": query_id,
            "parsed_intent": completed_intent,
            "followup_questions": next_questions,
            "status": "followups_ready",
            "questions_asked_count": next_questions_count,
            "max_followup_questions": max_followup_questions,
            "done": False,
        }

    return await _create_shopping_list(
        query_id=query_id,
        query_oid=oid,
        completed_intent=completed_intent,
        followup_text=followup_text,
        questions_asked_count=next_questions_count,
        max_followup_questions=max_followup_questions,
        list_model=list_model,
    )


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
