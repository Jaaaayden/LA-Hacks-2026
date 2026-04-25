from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "intent_parser.txt"
_INTENT_TOOL_NAME = "return_parsed_intent"

# Default shape for demos/tests; callers may pass any skeleton instead.
INTENT_SKELETON: dict[str, Any] = {
    "hobby": None,
    "budget_usd": None,
    "location": None,
    "skill_level": None,
    "age": None,
    "other": None,
}


def _skeleton_for_model(skeleton: dict[str, Any]) -> dict[str, Any]:
    """Keys the model fills; ``raw_query`` is always supplied by the server after parsing."""
    return {k: v for k, v in skeleton.items() if k != "raw_query"}


def _tool_property_schema(key: str) -> dict[str, Any]:
    """``other`` is reserved for hobby-specific flags (``gen_followup``), not the parser."""
    if key == "other":
        return {"type": "null"}
    return {}


def _build_intent_tool(fillable: dict[str, Any]) -> dict[str, Any]:
    keys = list(fillable.keys())
    if not keys:
        raise ValueError("skeleton must contain at least one fillable key (excluding raw_query only)")
    return {
        "name": _INTENT_TOOL_NAME,
        "description": (
            "Return the intent object: same keys as the template; replace nulls from the "
            "user message to the best of your ability; keep null when unsupported."
        ),
        "input_schema": {
            "type": "object",
            "properties": {k: _tool_property_schema(k) for k in keys},
            "required": keys,
            "additionalProperties": False,
        },
    }


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _merge_intent_payload(
    tool_input: dict[str, Any],
    skeleton: dict[str, Any],
    raw_query: str,
) -> dict[str, Any]:
    """Overlay tool output onto ``skeleton``; unknown keys ignored; ``raw_query`` always set from ``text``."""
    out: dict[str, Any] = dict(skeleton)
    fillable = _skeleton_for_model(skeleton)
    for key in fillable:
        if key in tool_input:
            out[key] = tool_input[key]
    if "other" in fillable:
        out["other"] = None
    out["raw_query"] = raw_query
    return out


def _user_message_for_parse(text: str, fillable: dict[str, Any]) -> str:
    template_block = json.dumps(fillable, indent=2)
    return (
        "Below is the intent template. Fill it from the user message — "
        "replace nulls only where you can do so reasonably; keep null otherwise.\n\n"
        f"Template:\n{template_block}\n\n"
        f"User message:\n{text}"
    )


def parse_intent(
    text: str,
    skeleton: dict[str, Any],
    *,
    model: str = "claude-sonnet-4-5",
) -> dict[str, Any]:
    """Fill ``skeleton`` from natural language via Claude. ``raw_query`` is always set to ``text``."""
    fillable = _skeleton_for_model(skeleton)
    if not fillable:
        raise ValueError(
            "skeleton must include at least one key to fill (e.g. hobby); "
            "only raw_query is not enough."
        )

    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)
    tool = _build_intent_tool(fillable)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=_load_system_prompt(),
        tools=[tool],
        tool_choice={"type": "tool", "name": _INTENT_TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": _user_message_for_parse(text, fillable),
            }
        ],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == _INTENT_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            return _merge_intent_payload(payload, skeleton, text)

    raise ValueError("Claude did not return structured tool output.")


def parse_intent_json(
    text: str,
    skeleton: dict[str, Any],
    *,
    model: str = "claude-sonnet-4-5",
) -> str:
    """Same as ``parse_intent`` but returns a JSON string."""
    return json.dumps(parse_intent(text, skeleton, model=model), indent=2)


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else "I want to try photography under $300"
    print(parse_intent_json(q, INTENT_SKELETON))
