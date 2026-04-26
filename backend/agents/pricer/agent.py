"""Hobbyist Pricer agent — Phase 4 deal scoring.

Receives a batch of listings (op="score") from Coordinator, computes a
median comp price per (hobby, item_type) by querying the listings
collection, scores each listing against its comp, and replies with
op="score_result". If a human chats it directly via ASI:One, returns
plain-English help so it stays independently demoable.

Run (standalone):
    .venv/bin/python -m backend.agents.pricer.agent

Normally launched together with Coordinator + Scout via
    bash scripts/run_agents.sh

Required env:
    PRICER_SEED            — random string; keep stable once registered
    AGENTVERSE_API_KEY     — same as the other agents
    MONGODB_URI            — listings collection lives in Mongo Atlas
"""

# bootstrap MUST be first (loads .env before kitscout.db touches Mongo).
from backend.agents.common import bootstrap  # noqa: F401

import os
from datetime import datetime, timezone
from pathlib import Path

_README_PATH = str(Path(__file__).parent / "README.md")
from typing import Any

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
from backend.agents.pricer.reasoning import reasons_for_listings
from backend.agents.pricer.scoring import median, score_listing
from backend.kitscout.db import listings


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


agent = Agent(
    name="hobbyist-pricer",
    seed=_require_env("PRICER_SEED"),
    port=8003,
    mailbox=True,
    publish_agent_details=True,
    readme_path=_README_PATH,
    description=(
        "Hobbyist Pricer — scores used-gear listings against the median "
        "for the same hobby + item type. Returns 'GREAT DEAL / FAIR / "
        "ABOVE MARKET' verdicts with percent below/above median. Called "
        "by the Hobbyist Coordinator after a kit search."
    ),
)

chat_proto = Protocol(spec=chat_protocol_spec)


_HELP_TEXT = (
    "Hi! I'm Hobbyist Pricer — I score used-gear listings against the median "
    "for the same hobby + item type. I'm called by the Hobbyist Coordinator, "
    "but you can ping me with a JSON op like:\n"
    '  {"op": "score", "listings": [{"hobby": "snowboarding", '
    '"item_type": "boots", "price_usd": 45}]}'
)


# Cache medians per (hobby, item_type) for the lifetime of one score request.
# Fresh per-request keeps the math correct if the listings table churns.
async def _comp_medians(
    needed: set[tuple[str, str]],
) -> dict[tuple[str, str], float | None]:
    """Compute median price_usd for each (hobby, item_type) pair."""
    out: dict[tuple[str, str], float | None] = {}
    for hobby, item_type in needed:
        if not hobby or not item_type:
            out[(hobby, item_type)] = None
            continue
        cursor = listings.find(
            {"hobby": hobby, "item_type": item_type},
            {"price_usd": 1},
        )
        prices = [
            float(doc["price_usd"])
            for doc in await cursor.to_list(length=200)
            if isinstance(doc.get("price_usd"), (int, float))
        ]
        out[(hobby, item_type)] = median(prices)
    return out


def _score_batch(
    incoming: list[dict[str, Any]],
    medians: dict[tuple[str, str], float | None],
) -> list[dict[str, Any]]:
    scored = []
    for lst in incoming:
        hobby = lst.get("hobby")
        item_type = lst.get("item_type")
        comp = medians.get((hobby, item_type))
        verdict = score_listing(lst.get("price_usd"), comp)
        scored.append({**lst, **verdict, "median_price_usd": comp})
    return scored


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # Ack first — Chat Protocol contract.
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    raw = extract_text(msg).strip()
    text = strip_agent_handle(raw).strip()
    ctx.logger.info(f"[pricer chat] from {sender[:14]}…: {text[:120]!r}")

    op_msg = parse_json_op(text)
    if op_msg is None or op_msg.get("op") != "score":
        await ctx.send(sender, make_text_message(_HELP_TEXT))
        return

    request_id = op_msg.get("request_id")
    incoming = op_msg.get("listings") or []
    if not isinstance(incoming, list):
        await send_json(
            ctx,
            sender,
            {
                "op": "score_error",
                "request_id": request_id,
                "error": "listings must be a list",
            },
        )
        return

    try:
        # Hydrate the hobby for any listing missing it from the message
        # body — Coordinator passes top-level hobby once for the whole batch.
        default_hobby = op_msg.get("hobby")
        for lst in incoming:
            lst.setdefault("hobby", default_hobby)

        needed = {
            (lst.get("hobby") or "", lst.get("item_type") or "")
            for lst in incoming
        }
        medians_map = await _comp_medians(needed)
        scored = _score_batch(incoming, medians_map)

        # One batched LLM call to produce a one-line reason per listing.
        # Sync Anthropic blocks the loop ~1-3s; acceptable for single-user
        # demo traffic. Soft-fail to empty reasons if the call errors.
        try:
            user_attributes = op_msg.get("user_attributes") or None
            reasons = reasons_for_listings(
                scored,
                hobby=default_hobby,
                user_attributes=user_attributes,
            )
            for lst, reason in zip(scored, reasons):
                if reason:
                    lst["reason"] = reason
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning(f"[pricer reasoning] skipped: {exc}")

        ctx.logger.info(
            f"[pricer score] req={request_id} n={len(scored)} "
            f"comps={sum(1 for v in medians_map.values() if v is not None)} "
            f"reasons={sum(1 for s in scored if s.get('reason'))}"
        )
        await send_json(
            ctx,
            sender,
            {
                "op": "score_result",
                "request_id": request_id,
                "scored": scored,
            },
        )
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[pricer score] error: {exc}")
        await send_json(
            ctx,
            sender,
            {
                "op": "score_error",
                "request_id": request_id,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


agent.include(chat_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()
