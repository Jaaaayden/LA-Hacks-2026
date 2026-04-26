import json
import os
import sys
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "list_generator.txt"
_SHOPPING_LIST_TOOL_NAME = "return_shopping_list"
_SHOPPING_LIST_TOOL = {
    "name": _SHOPPING_LIST_TOOL_NAME,
    "description": "Equipment shopping list for the hobby described by the intent JSON.",
    "input_schema": {
        "type": "object",
        "properties": {
            "hobby": {"type": "string"},
            "budget_usd": {"type": ["number", "null"]},
            "items": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "item_type": {"type": "string"},
                        "search_query": {
                            "type": "string",
                            "description": (
                                "Marketplace search phrase including the item type "
                                "and the most important buying attributes."
                            ),
                        },
                        "required": {"type": "boolean"},
                        "attributes": {
                            "type": "array",
                            "description": (
                                "Flexible key/value product specs needed to buy this item, "
                                "such as species, size, style, compatibility, mount, "
                                "material, capacity, or season rating."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {
                                        "type": "string",
                                        "description": "Short snake_case product spec name.",
                                    },
                                    "value": {
                                        "type": "array",
                                        "description": (
                                            "One or more acceptable product spec values "
                                            "to match in listings, each with its own "
                                            "justification."
                                        ),
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "value": {
                                                    "type": "string",
                                                    "description": "Product spec value to match.",
                                                },
                                                "justification": {
                                                    "type": "string",
                                                    "description": (
                                                        "Brief reason why this specific "
                                                        "value was chosen."
                                                    ),
                                                },
                                            },
                                            "required": ["value", "justification"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["key", "value"],
                                "additionalProperties": False,
                            },
                        },
                        "notes": {"type": ["string", "null"]},
                    },
                    "required": [
                        "item_type",
                        "search_query",
                        "required",
                        "attributes",
                        "notes",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["hobby", "budget_usd", "items"],
        "additionalProperties": False,
    },
}


def _validate_shopping_list(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Claude returned an incomplete shopping list: missing items")
    return payload


def _request_shopping_list(
    client: Anthropic,
    model: str,
    system: str,
    user_content: str,
) -> dict[str, Any]:
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        tools=[_SHOPPING_LIST_TOOL],
        tool_choice={"type": "tool", "name": _SHOPPING_LIST_TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": user_content,
            }
        ],
    )

    for block in msg.content:
        if block.type == "tool_use" and block.name == _SHOPPING_LIST_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            return _validate_shopping_list(payload)

    raise ValueError("Claude did not return shopping list tool output.")


def _as_dict(intent: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(intent, str):
        parsed = json.loads(intent)
    else:
        parsed = intent
    if not isinstance(parsed, dict):
        raise ValueError("intent must be a JSON object or dict")
    return parsed


def gen_list(
    intent: str | dict[str, Any],
    model: str = "claude-sonnet-4-5",
) -> dict[str, Any]:
    """Generate a predictable equipment shopping list from normalized intent JSON."""
    d = _as_dict(intent)
    hobby = d.get("hobby")
    if not hobby:
        raise ValueError("intent must include a hobby")

    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=key)
    system = PROMPT_PATH.read_text(encoding="utf-8").strip()
    user_content = "Intent JSON:\n" + json.dumps(d, indent=2)
    try:
        return _request_shopping_list(client, model, system, user_content)
    except ValueError as exc:
        retry_content = (
            f"{user_content}\n\n"
            f"Previous output was invalid: {exc}\n"
            "Return the complete shopping list now. The top-level object must include "
            "hobby, budget_usd, and a non-empty items array."
        )
        return _request_shopping_list(client, model, system, retry_content)


if __name__ == "__main__":
    sample = """
{
  "hobby": "snowboarding",
  "budget_usd": 400,
  "location": "Los Angeles",
  "skill_level": "beginner",
  "other": [
    {
      "key": "rider_level",
      "label": "Rider level (beginner/intermediate/advanced)",
      "value": "beginner"
    },
    {
      "key": "board_length",
      "label": "Board length (cm)",
      "value": "155"
    },
    {
      "key": "boot_size",
      "label": "Boot size",
      "value": "10"
    },
    {
      "key": "riding_style",
      "label": "Riding style (all-mountain/freestyle/powder)",
      "value": "all-mountain"
    },
    {
      "key": "needs_bindings",
      "label": "Needs bindings included",
      "value": "yes"
    }
  ],
  "raw_query": "I want to snowboard, maybe $400 max"
}
"""
    arg = sys.argv[1] if len(sys.argv) > 1 else sample
    print(json.dumps(gen_list(arg), indent=2))
