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
                "items": {
                    "type": "object",
                    "properties": {
                        "item_type": {"type": "string"},
                        "required": {"type": "boolean"},
                        "requirements": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "key": {"type": "string"},
                                    "label": {"type": "string"},
                                    "value": {"type": "string"},
                                },
                                "required": ["key", "label", "value"],
                                "additionalProperties": False,
                            },
                        },
                        "notes": {"type": ["string", "null"]},
                    },
                    "required": ["item_type", "required", "requirements", "notes"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["hobby", "budget_usd", "items"],
        "additionalProperties": False,
    },
}


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
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        system=PROMPT_PATH.read_text(encoding="utf-8").strip(),
        tools=[_SHOPPING_LIST_TOOL],
        tool_choice={"type": "tool", "name": _SHOPPING_LIST_TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": "Intent JSON:\n" + json.dumps(d, indent=2),
            }
        ],
    )

    for block in msg.content:
        if block.type == "tool_use" and block.name == _SHOPPING_LIST_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            return payload

    raise ValueError("Claude did not return shopping list tool output.")


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
