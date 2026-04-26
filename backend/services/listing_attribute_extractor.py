import json
import os
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

from backend.services.listing_store import parse_platform_id

PROMPT_PATH = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "listing_attribute_extractor.txt"
)
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_TOOL_NAME = "return_listing_attribute_analyses"
_TOOL: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": "Extract listing facts, missing fields, and seller questions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "analyses": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "listing_id": {"type": "string"},
                        "relevance": {
                            "type": "string",
                            "enum": ["relevant", "uncertain", "irrelevant"],
                        },
                        "extracted_attributes": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "value": {"type": "string"},
                                    "source": {
                                        "type": "string",
                                        "enum": [
                                            "title",
                                            "description",
                                            "condition",
                                            "category",
                                            "price",
                                            "seller",
                                            "fulfillment",
                                            "inferred_from_listing",
                                        ],
                                    },
                                    "confidence": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": [
                                    "key",
                                    "value",
                                    "source",
                                    "confidence",
                                ],
                                "additionalProperties": False,
                            },
                        },
                        "missing_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "seller_questions": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field": {"type": "string"},
                                    "question": {"type": "string"},
                                    "priority": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["field", "question", "priority"],
                                "additionalProperties": False,
                            },
                        },
                        "notes": {"type": "string"},
                    },
                    "required": [
                        "listing_id",
                        "relevance",
                        "extracted_attributes",
                        "missing_fields",
                        "seller_questions",
                        "notes",
                    ],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["analyses"],
        "additionalProperties": False,
    },
}


def _shopping_item_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "item_type": item.get("item_type"),
        "search_query": item.get("search_query"),
        "budget_usd": item.get("budget_usd"),
        "required": item.get("required"),
        "attributes": item.get("attributes") or [],
        "notes": item.get("notes"),
    }


def _listing_payload(listing: dict[str, Any]) -> dict[str, Any] | None:
    listing_id = parse_platform_id(str(listing.get("url") or ""))
    if not listing_id:
        return None

    category = listing.get("category") if isinstance(listing.get("category"), dict) else {}
    seller = listing.get("seller") if isinstance(listing.get("seller"), dict) else {}
    fulfillment = (
        listing.get("fulfillment")
        if isinstance(listing.get("fulfillment"), dict)
        else {}
    )

    return {
        "listing_id": listing_id,
        "title": listing.get("title"),
        "description": listing.get("description"),
        "price": listing.get("price"),
        "condition": listing.get("condition"),
        "condition_code": listing.get("condition_code"),
        "location": listing.get("location"),
        "category": {
            "name": category.get("name"),
            "l1_name": category.get("l1_name"),
            "l2_name": category.get("l2_name"),
            "l3_name": category.get("l3_name"),
            "attributes": category.get("attributes") or [],
        },
        "seller": {
            "name": seller.get("name"),
            "rating_average": seller.get("rating_average"),
            "rating_count": seller.get("rating_count"),
            "response_time": seller.get("response_time"),
        },
        "fulfillment": fulfillment,
    }


def _dedupe_strings(values: list[Any], *, limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        key = text.lower()
        if not text or key in seen:
            continue
        out.append(text)
        seen.add(key)
        if len(out) >= limit:
            break
    return out


def _normalize_analysis(row: dict[str, Any]) -> dict[str, Any] | None:
    listing_id = str(row.get("listing_id") or "").strip()
    if not listing_id:
        return None

    attributes: list[dict[str, str]] = []
    seen_attr_keys: set[tuple[str, str]] = set()
    for attr in row.get("extracted_attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = str(attr.get("key") or "").strip()
        value = str(attr.get("value") or "").strip()
        if not key or not value:
            continue
        dedupe_key = (key.lower(), value.lower())
        if dedupe_key in seen_attr_keys:
            continue
        attributes.append(
            {
                "key": key,
                "value": value,
                "source": str(attr.get("source") or "inferred_from_listing"),
                "confidence": str(attr.get("confidence") or "medium"),
            }
        )
        seen_attr_keys.add(dedupe_key)
        if len(attributes) >= 8:
            break

    questions: list[dict[str, str]] = []
    seen_question_text: set[str] = set()
    for question in row.get("seller_questions") or []:
        if not isinstance(question, dict):
            continue
        text = str(question.get("question") or "").strip()
        if not text or text.lower() in seen_question_text:
            continue
        questions.append(
            {
                "field": str(question.get("field") or "details").strip(),
                "question": text,
                "priority": str(question.get("priority") or "medium"),
            }
        )
        seen_question_text.add(text.lower())
        if len(questions) >= 3:
            break

    return {
        "listing_id": listing_id,
        "relevance": row.get("relevance") or "uncertain",
        "extracted_attributes": attributes,
        "missing_fields": _dedupe_strings(row.get("missing_fields") or [], limit=5),
        "seller_questions": questions,
        "attribute_notes": str(row.get("notes") or "").strip(),
    }


def extract_listing_attributes(
    listings: list[dict[str, Any]],
    *,
    shopping_item: dict[str, Any],
    hobby: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, dict[str, Any]]:
    """Return listing analyses keyed by OfferUp platform id."""
    compact_listings = [
        payload for listing in listings if (payload := _listing_payload(listing))
    ]
    if not compact_listings:
        return {}

    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    user_payload = {
        "hobby": hobby,
        "shopping_item": _shopping_item_payload(shopping_item),
        "listings": compact_listings,
    }

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=PROMPT_PATH.read_text(encoding="utf-8").strip(),
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": json.dumps(user_payload, indent=2)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            analyses: dict[str, dict[str, Any]] = {}
            for row in payload.get("analyses") or []:
                if not isinstance(row, dict):
                    continue
                normalized = _normalize_analysis(row)
                if normalized:
                    analyses[normalized["listing_id"]] = normalized
            return analyses

    raise ValueError("Claude did not return listing attribute analyses.")
