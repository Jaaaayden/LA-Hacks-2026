import json
import os
import re
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "followup.txt"
OTHER_FLAGS_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "other_flags.txt"
_OTHER_FLAGS_TOOL_NAME = "return_other_flags"
_OTHER_FLAGS_TOOL = {
    "name": _OTHER_FLAGS_TOOL_NAME,
    "description": "Hobby-specific slots for intent.other (array of flag objects).",
    "input_schema": {
        "type": "object",
        "properties": {
            "flags": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string"},
                        "label": {"type": "string"},
                    },
                    "required": ["key", "label"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["flags"],
        "additionalProperties": False,
    },
}


def _as_dict(intent):
    if isinstance(intent, str):
        return json.loads(intent)
    return intent


def _has_nulls(intent):
    for k, v in _as_dict(intent).items():
        if k != "raw_query" and v is None:
            return True
    return False


def _needs_followup_questions(intent, other_flags):
    flags = other_flags if other_flags else []
    return _has_nulls(intent) or bool(flags)


def _raw_query_text(raw_query):
    if isinstance(raw_query, list):
        return "\n".join(str(q) for q in raw_query if q)
    return str(raw_query or "")


def _questions_blob_to_list(text: str) -> list[str]:
    """Turn numbered LLM output into plain strings (one question per list item)."""
    t = (text or "").strip()
    if not t:
        return []
    if "no follow-up" in t.lower():
        return []
    chunks = re.split(r"\n+(?=\s*\d+\.\s)", t)
    out: list[str] = []
    for ch in chunks:
        stripped = re.sub(r"^\s*\d+\.\s*", "", ch.strip(), count=1)
        if stripped:
            out.append(stripped)
    return out


def followup_questions_from_intent(intent, other_flags=None, model="claude-sonnet-4-5"):
    flags = list(other_flags) if other_flags else []
    if not _needs_followup_questions(intent, flags):
        return "No follow-up questions needed."

    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    system = PROMPT_PATH.read_text(encoding="utf-8").strip()
    blob = json.dumps(_as_dict(intent), indent=2)
    user_body = f"Intent JSON:\n{blob}"
    if flags:
        user_body += "\n\nHobby-specific flags (one follow-up question each):\n"
        user_body += json.dumps(flags, indent=2)
    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user_body}],
    )
    for block in msg.content:
        if block.type == "text":
            return block.text.strip()
    raise ValueError("Claude returned no text.")


def suggest_other_flags_for_hobby(hobby, raw_query="", model="claude-sonnet-4-5"):
    """
    Return a list of dicts like {"key": "shoe_size", "label": "US shoe size", "value": None}
    for intent["other"], based on the hobby (LLM).
    """
    h = (hobby or "").strip()
    if not h:
        return []

    load_dotenv()
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    system = OTHER_FLAGS_PROMPT_PATH.read_text(encoding="utf-8").strip()
    user_parts = [f"Hobby: {h}"]
    rq = _raw_query_text(raw_query).strip()
    if rq:
        user_parts.append(f"User message:\n{rq}")
    user = "\n\n".join(user_parts)

    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        tools=[_OTHER_FLAGS_TOOL],
        tool_choice={"type": "tool", "name": _OTHER_FLAGS_TOOL_NAME},
        messages=[{"role": "user", "content": user}],
    )
    for block in msg.content:
        if block.type == "tool_use" and block.name == _OTHER_FLAGS_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            flags = payload.get("flags") or []
            out = []
            for row in flags:
                if not isinstance(row, dict):
                    continue
                k = row.get("key")
                if not k:
                    continue
                out.append(
                    {
                        "key": str(k).strip(),
                        "label": str(row.get("label") or k).strip(),
                        "value": None,
                    }
                )
            return out
    raise ValueError("Claude did not return other_flags tool output.")


def gen_followup(
    intent,
    include_hobby_other_flags=False,
    model="claude-sonnet-4-5",
    merged_intent_out=None,
):
    """
    Returns ``{"questions": [...]}`` — one string per null intent field (except
    ``raw_query``) and per hobby flag when enabled.

    Merged intent (same keys as input; ``other`` filled with flag rows when
    ``include_hobby_other_flags`` is True) is **not** in the return value. Pass an
    empty dict as ``merged_intent_out`` to receive that document in-place for DB writes
    (the dict is cleared, then updated with the merged intent fields).
    """
    d = _as_dict(intent)
    flags: list[dict] = []
    if include_hobby_other_flags:
        flags = suggest_other_flags_for_hobby(
            d.get("hobby") or "",
            d.get("raw_query") or "",
            model=model,
        )
    questions_blob = followup_questions_from_intent(
        intent, other_flags=flags, model=model
    )
    questions = _questions_blob_to_list(questions_blob)

    if merged_intent_out is not None:
        merged = dict(d)
        if include_hobby_other_flags:
            merged["other"] = list(flags)
        merged_intent_out.clear()
        merged_intent_out.update(merged)

    return {"questions": questions}


if __name__ == "__main__":
    sample = (
        '{"hobby": "snowboarding", "budget_usd": null, "location": null, '
        '"skill_level": "beginner", "age": null, "other": null, '
        '"raw_query": "I want to snowboard"}'
    )
    arg = sys.argv[1] if len(sys.argv) > 1 else sample
    print(json.dumps(gen_followup(arg, include_hobby_other_flags=True), indent=2))
