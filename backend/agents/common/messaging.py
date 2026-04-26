"""Helpers for Chat Protocol message construction and parsing.

Inter-agent traffic uses plain ChatMessage objects with structured JSON in
TextContent.text — keeps Scout/Pricer chattable in ASI:One when humans hit
them directly (they fall back to plain-English help if JSON-parse fails).
"""

import json
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    EndSessionContent,
    TextContent,
)


def make_text_message(text: str, *, end_session: bool = False) -> ChatMessage:
    content = [TextContent(type="text", text=text)]
    if end_session:
        content.append(EndSessionContent(type="end-session"))
    return ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=content,
    )


def extract_text(msg: ChatMessage) -> str:
    """Concatenate all TextContent blocks in a ChatMessage."""
    return "".join(c.text for c in msg.content if isinstance(c, TextContent))


async def send_text(ctx, to: str, text: str, *, end_session: bool = False):
    """Convenience: send a plain-text ChatMessage to a peer."""
    return await ctx.send(to, make_text_message(text, end_session=end_session))


async def send_json(ctx, to: str, payload: dict[str, Any]):
    """Convenience: send a JSON-encoded payload as a ChatMessage to a peer."""
    return await ctx.send(to, make_text_message(json.dumps(payload)))


def parse_json_op(text: str) -> dict[str, Any] | None:
    """Try to parse text as a structured JSON op message.

    Returns the parsed dict on success, or None if the text is not JSON or
    not a dict. Lets Scout/Pricer detect human chats vs. inter-agent ops.
    """
    if not text:
        return None
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


# ASI:One and the Agentverse Inspector prepend the recipient's @-handle to
# every message ("@hobbyist hello" / "@agent1q0z... hello"). Strip a single
# leading @-token if it looks like an agent reference so it never reaches
# the LLM parser. Only matches our known prefixes (agent1, hobbyist) — a
# legitimate "@home" or "@9am" still passes through.
_AGENT_HANDLE_RE = re.compile(r"^\s*@(?:agent1\S+|hobbyist\S*)\s*")


def strip_agent_handle(text: str) -> str:
    """Remove a leading agent @-handle if the chat client added one."""
    return _AGENT_HANDLE_RE.sub("", text or "", count=1)
