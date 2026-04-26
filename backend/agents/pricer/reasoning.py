"""LLM-generated one-line deal reasoning for Pricer.

A pure-numeric `28% below median` verdict reads like a lookup, not advice.
This module sends a single batched Claude call that produces a concise
human-friendly reason per listing, blending the comp price, condition,
title cues, and user fit.

Deliberately one batched call (not per-listing) so latency stays near a
single round-trip even with 8-10 listings, and so the LLM can compare
listings against each other when ranking is on the line.
"""

import json
import os
from typing import Any

from anthropic import Anthropic

_REASONING_TOOL_NAME = "return_listing_reasons"
_REASONING_TOOL = {
    "name": _REASONING_TOOL_NAME,
    "description": (
        "Return a one-line reasoning string per input listing, in the "
        "same order. Each reason is a single sentence (max ~120 chars) "
        "explaining whether this is a good buy and why, weighing price "
        "vs median, condition, title cues, and user fit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
            }
        },
        "required": ["reasons"],
        "additionalProperties": False,
    },
}


_SYSTEM_PROMPT = (
    "You score used-marketplace listings for hobbyists buying secondhand "
    "gear. Given each listing's title, price, item type, comp median, and "
    "the user's parsed attributes (size, skill level, riding style, etc.), "
    "write ONE short sentence explaining whether the listing is a good buy.\n"
    "\n"
    "Rules:\n"
    "- Be concrete: cite the price vs the median, and the most relevant "
    "  detail from the title (brand, model, size, condition).\n"
    "- If the user's attributes are listed and the title matches one "
    "  (e.g. 'size 9' matches user.boot_size=9), call that out.\n"
    "- If the title hints at poor condition (cracked, broken, parts only), "
    "  recommend skipping even if the price looks good.\n"
    "- Keep each reason under ~120 characters.\n"
    "- Don't restate the deal label (GREAT DEAL / FAIR / etc.) — the UI "
    "  already shows that. Add the WHY.\n"
    "- Return one reason per listing in the same order as the input."
)


def _build_user_payload(
    scored_listings: list[dict[str, Any]],
    hobby: str | None,
    user_attributes: dict[str, str] | None,
) -> str:
    body = {
        "hobby": hobby,
        "user_attributes": user_attributes or {},
        "listings": [
            {
                "i": i,
                "item_type": lst.get("item_type"),
                "title": lst.get("title"),
                "price_usd": lst.get("price_usd"),
                "median_price_usd": lst.get("median_price_usd"),
                "label": lst.get("label"),
                "pct_below_median": lst.get("pct_below_median"),
            }
            for i, lst in enumerate(scored_listings)
        ],
    }
    return json.dumps(body, indent=2)


def reasons_for_listings(
    scored_listings: list[dict[str, Any]],
    *,
    hobby: str | None = None,
    user_attributes: dict[str, str] | None = None,
    model: str = "claude-haiku-4-5-20251001",
    max_tokens: int = 2048,
) -> list[str]:
    """Return a list of one-line reasons aligned to `scored_listings`.

    Defaults to Haiku 4.5 — fast, cheap, plenty smart for a one-liner.
    Returns empty strings for any listing the LLM didn't produce a reason
    for (so the formatter never crashes on missing entries).
    """
    if not scored_listings:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return [""] * len(scored_listings)

    client = Anthropic(api_key=api_key)
    user_body = _build_user_payload(scored_listings, hobby, user_attributes)

    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=_SYSTEM_PROMPT,
        tools=[_REASONING_TOOL],
        tool_choice={"type": "tool", "name": _REASONING_TOOL_NAME},
        messages=[{"role": "user", "content": user_body}],
    )

    for block in msg.content:
        if block.type == "tool_use" and block.name == _REASONING_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            reasons = payload.get("reasons") or []
            # Pad / truncate to align with input length.
            normalized = list(reasons)[: len(scored_listings)]
            normalized += [""] * (len(scored_listings) - len(normalized))
            return [str(r or "") for r in normalized]

    return [""] * len(scored_listings)
