from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "negotiator.txt"
_NEGOTIATION_TOOL_NAME = "decide_next_action"
_NEGOTIATION_TOOL: dict[str, Any] = {
    "name": _NEGOTIATION_TOOL_NAME,
    "description": (
        "Decide the next negotiation action: send a message, accept the deal, "
        "or give up. Return action and the message to send (null when giving up)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["send", "accept", "give_up"],
                "description": (
                    "send: generate and send the next message. "
                    "accept: the price is acceptable; send a closing message. "
                    "give_up: seller is firm; do not send anything more."
                ),
            },
            "message": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "description": (
                    "The message text to send. Required when action is 'send' or 'accept'. "
                    "Must be null when action is 'give_up'."
                ),
            },
        },
        "required": ["action", "message"],
        "additionalProperties": False,
    },
}


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8").strip()


def _build_user_message(
    listing_title: str,
    asking_price_usd: float,
    target_price_usd: float,
    conversation: list[dict[str, str]],
) -> str:
    lines: list[str] = [
        f"Listing: {listing_title}",
        f"Asking price: ${asking_price_usd:.2f}",
        f"Target price: ${target_price_usd:.2f}",
    ]
    if not conversation:
        lines.append("\nConversation: (none — this is the opening message)")
    else:
        lines.append("\nConversation so far:")
        for turn in conversation:
            role = turn["role"].capitalize()
            lines.append(f"{role}: {turn['content']}")
    return "\n".join(lines)


def gen_negotiation_message(
    listing_title: str,
    asking_price_usd: float,
    target_price_usd: float,
    conversation: list[dict[str, str]],
    model: str = "claude-haiku-4-5-20251001",
) -> dict[str, str | None]:
    """Generate the next negotiation action via Claude.

    Args:
        listing_title: The OfferUp listing title.
        asking_price_usd: Seller's listed price.
        target_price_usd: Buyer's goal/budget price.
        conversation: Ordered list of {"role": "negotiator"|"seller", "content": str}.
        model: Anthropic model to use.

    Returns:
        {"action": "send"|"accept"|"give_up", "message": str | None}
    """
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set")

    client = Anthropic(api_key=api_key)
    user_message = _build_user_message(
        listing_title, asking_price_usd, target_price_usd, conversation
    )

    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=_load_system_prompt(),
        tools=[_NEGOTIATION_TOOL],
        tool_choice={"type": "tool", "name": _NEGOTIATION_TOOL_NAME},
        messages=[{"role": "user", "content": user_message}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == _NEGOTIATION_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            action = payload.get("action", "give_up")
            message = payload.get("message")
            if action == "give_up":
                message = None
            return {"action": action, "message": message}

    raise ValueError("Claude did not return structured tool output.")
