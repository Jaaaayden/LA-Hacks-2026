from __future__ import annotations

import json
import os
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
_TOOL_NAME = "return_seller_reply_enrichment"
_TOOL: dict[str, Any] = {
    "name": _TOOL_NAME,
    "description": "Extract listing facts answered by a seller reply.",
    "input_schema": {
        "type": "object",
        "properties": {
            "extracted_attributes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "value": {"type": "string"},
                        "source": {"type": "string", "enum": ["seller_reply"]},
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                        },
                    },
                    "required": ["key", "value", "source", "confidence"],
                    "additionalProperties": False,
                },
            },
            "satisfied_missing_fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Missing-field names that this seller reply answered.",
            },
            "notes": {
                "type": "string",
                "description": "Short summary of useful seller-provided details.",
            },
        },
        "required": ["extracted_attributes", "satisfied_missing_fields", "notes"],
        "additionalProperties": False,
    },
}


def enrich_listing_from_seller_reply(
    *,
    listing: dict[str, Any],
    bargain_item: dict[str, Any],
    seller_reply: str,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Extract concrete listing details from a seller reply."""
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    payload = {
        "task": (
            "Extract only concrete facts the seller just provided. Focus on missing "
            "details like size, age, model, wear, defects, included parts, availability, "
            "and pickup/shipping constraints. Do not infer facts that are not stated."
        ),
        "listing": {
            "title": listing.get("title"),
            "description": listing.get("description"),
            "price_usd": listing.get("price_usd"),
            "condition": listing.get("condition"),
            "size": listing.get("size"),
            "extracted_attributes": listing.get("extracted_attributes") or [],
            "missing_fields": listing.get("missing_fields") or [],
            "seller_questions": listing.get("seller_questions") or [],
        },
        "selected_item": {
            "item_type": bargain_item.get("item_type"),
            "last_message": bargain_item.get("last_message"),
        },
        "seller_reply": seller_reply,
    }

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": _TOOL_NAME},
        messages=[{"role": "user", "content": json.dumps(payload, indent=2)}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == _TOOL_NAME:
            raw = block.input if isinstance(block.input, dict) else dict(block.input)
            return _normalize_enrichment(raw)

    raise ValueError("Claude did not return seller reply enrichment.")


def _normalize_enrichment(raw: dict[str, Any]) -> dict[str, Any]:
    attributes: list[dict[str, str]] = []
    seen_attrs: set[tuple[str, str]] = set()
    for row in raw.get("extracted_attributes") or []:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        value = str(row.get("value") or "").strip()
        if not key or not value:
            continue
        dedupe_key = (key.lower(), value.lower())
        if dedupe_key in seen_attrs:
            continue
        seen_attrs.add(dedupe_key)
        attributes.append(
            {
                "key": key,
                "value": value,
                "source": "seller_reply",
                "confidence": str(row.get("confidence") or "medium"),
            }
        )
        if len(attributes) >= 8:
            break

    fields: list[str] = []
    seen_fields: set[str] = set()
    for field in raw.get("satisfied_missing_fields") or []:
        text = str(field or "").strip()
        key = text.lower()
        if text and key not in seen_fields:
            fields.append(text)
            seen_fields.add(key)

    return {
        "extracted_attributes": attributes,
        "satisfied_missing_fields": fields[:8],
        "notes": str(raw.get("notes") or "").strip(),
    }
