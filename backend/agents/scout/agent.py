"""Hobbyist Scout agent — Phase 3 Mongo listing search.

Receives JSON-encoded ChatMessages from the Coordinator with op="search",
runs a Mongo lookup against the listings collection, and replies with
op="search_result". If a human chats it directly via ASI:One (non-JSON
text), it replies with a plain-English help message so it remains
independently demoable.

Run:
    .venv/bin/python -m backend.agents.scout.agent

Required env (in .env):
    SCOUT_SEED              — random string; keep stable once registered
    AGENTVERSE_API_KEY      — same as Coordinator's
    MONGODB_URI             — listings collection lives in Mongo Atlas
"""

# bootstrap MUST be first (loads .env before kitscout.db touches Mongo).
from backend.agents.common import bootstrap  # noqa: F401

import os
from datetime import datetime, timezone
from pathlib import Path

_README_PATH = str(Path(__file__).parent / "README.md")

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    chat_protocol_spec,
)

from backend.agents.common.messaging import (
    extract_text,
    make_text_message,
    parse_json_op,
    send_json,
    strip_agent_handle,
)
from backend.agents.scout.tools import mongo_search


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


agent = Agent(
    name="hobbyist-scout",
    seed=_require_env("SCOUT_SEED"),
    port=8002,
    mailbox=True,
    publish_agent_details=True,
    readme_path=_README_PATH,
    description=(
        "Hobbyist Scout — finds used Marketplace listings for hobby kit "
        "items. Tiered Mongo search with hobby + item-type fallback so "
        "every kit item surfaces real candidates. Called by the Hobbyist "
        "Coordinator; chattable directly with a JSON 'search' op."
    ),
)

chat_proto = Protocol(spec=chat_protocol_spec)


_HELP_TEXT = (
    "Hi! I'm Hobbyist Scout — I find used Marketplace listings for hobby "
    "kit items. I'm normally called by the Hobbyist Coordinator, but you "
    "can ping me with a JSON op like:\n"
    '  {"op": "search", "hobby": "snowboarding", "item_type": "snowboard", '
    '"max_price": 200}'
)


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # Always ack first so the Chat Protocol stays clean.
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    raw = extract_text(msg).strip()
    # JSON ops from Coordinator never have an @-handle prefix, but humans
    # chatting via ASI:One do — strip before deciding op vs. help.
    text = strip_agent_handle(raw).strip()
    ctx.logger.info(f"[scout chat] from {sender[:14]}…: {text[:120]!r}")

    op_msg = parse_json_op(text)
    if op_msg is None or op_msg.get("op") != "search":
        # Human chat or malformed payload — be helpful.
        await ctx.send(sender, make_text_message(_HELP_TEXT))
        return

    request_id = op_msg.get("request_id")
    item_type = op_msg.get("item_type")
    try:
        results = await mongo_search(
            hobby=op_msg.get("hobby"),
            item_type=item_type,
            # Prefer the new wire field; accept the old name for any payloads
            # left over from an upgrade in flight.
            list_id=op_msg.get("list_id") or op_msg.get("shopping_list_id"),
            item_id=op_msg.get("item_id"),
            max_price=op_msg.get("max_price"),
            attributes=op_msg.get("attributes") or None,
            limit=int(op_msg.get("limit") or 5),
        )
        ctx.logger.info(
            f"[scout search] item_type={item_type} hits={len(results)} "
            f"req={request_id}"
        )
        await send_json(
            ctx,
            sender,
            {
                "op": "search_result",
                "request_id": request_id,
                "item_type": item_type,
                "listings": results,
            },
        )
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[scout search] error: {exc}")
        await send_json(
            ctx,
            sender,
            {
                "op": "search_error",
                "request_id": request_id,
                "item_type": item_type,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()
