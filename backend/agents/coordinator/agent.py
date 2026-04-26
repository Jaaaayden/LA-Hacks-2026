"""Hobbyist Coordinator agent — Phase 2 intake → kit flow.

State machine (per ASI:One sender address):
    1. First message → start_query → reply with follow-up questions.
    2. Each subsequent message → finish_query → reply with either
       more follow-ups or the final shopping-list kit.
    3. After the kit lands, further messages are placeholders until
       Phase 3 wires Scout/Pricer for live listing search.

Run:
    .venv/bin/python -m backend.agents.coordinator.agent

Required env (in .env):
    COORDINATOR_SEED        — random string; keep stable once registered
    AGENTVERSE_API_KEY      — from https://agentverse.ai → Settings → API Keys
    ANTHROPIC_API_KEY       — used by intent_parser / gen_followup / gen_list
    MONGODB_URI             — query_flow persists sessions in Mongo
"""

# IMPORTANT: bootstrap MUST be first — it calls load_dotenv() before any
# downstream module touches MongoDB at import.
from backend.agents.common import bootstrap  # noqa: F401

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_README_PATH = str(Path(__file__).parent / "README.md")

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    chat_protocol_spec,
)
from uagents_core.contrib.protocols.payment import (
    CancelPayment,
    CommitPayment,
    CompletePayment,
    Funds,
    RequestPayment,
    payment_protocol_spec,
)

from backend.agents.common.addresses import (
    payment_sink_address,
    pricer_address,
    scout_address,
)
from backend.agents.common.messaging import (
    extract_text,
    make_text_message,
    parse_json_op,
    send_json,
    strip_agent_handle,
)
from backend.agents.common.session import ConversationStore
from backend.agents.common.tools import (
    fetch_shopping_list,
    finish_query,
    flatten_kit_for_chat,
    format_followup_questions,
    format_kit_with_listings,
    start_query,
)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


agent = Agent(
    name="hobbyist-coordinator",
    seed=_require_env("COORDINATOR_SEED"),
    port=8001,
    mailbox=True,
    publish_agent_details=True,
    readme_path=_README_PATH,
    description=(
        "Hobbyist Coordinator — turn 'I want to start <hobby>, $X, in <city>' "
        "into a curated kit of real used-marketplace listings. Multi-turn "
        "intake, dispatches to Scout + Pricer, optional Payment Protocol "
        "unlocks fresh scrapes. Hobbies: snowboarding, skateboarding, "
        "climbing, cycling, photography."
    ),
)

chat_proto = Protocol(spec=chat_protocol_spec)
# Payment Protocol — buyer role. Coordinator initiates a RequestPayment to
# the PaymentSink agent when the user asks for fresh listings. The
# RequestPayment → CommitPayment → CompletePayment cycle is what the
# Fetch.ai Agentverse track scores as "optional Payment Protocol".
payment_proto = Protocol(spec=payment_protocol_spec, role="buyer")
sessions = ConversationStore(ttl_minutes=30)

# Demo payment configuration. Amount is symbolic on testnet — we just need
# the protocol cycle to fire end-to-end with visible logs.
_PAYMENT_AMOUNT_FET = "0.5"
_PAYMENT_DEADLINE_S = 120

# Scout request/reply correlation — keyed by request_id we generate per fan-out
# call. Resolved when Scout replies with the matching request_id. Lives at
# module scope because uagents handlers run as separate coroutines and need
# to share state.
_pending: dict[str, asyncio.Future] = {}

# Per-item Scout fan-out timeout. 12s gives Mongo + relay headroom while
# bounding the worst-case user wait when Scout is unhealthy.
_SCOUT_TIMEOUT_S = 12.0

# Pricer is a single batched call — Mongo lookups for medians dominate.
_PRICER_TIMEOUT_S = 12.0


_INTENT_ATTRIBUTE_KEYS = (
    "skill_level", "age", "height", "weight", "boot_size", "shoe_size",
    "riding_style", "stance", "gender", "body_size",
)


def _flatten_user_attributes(parsed_intent: dict[str, Any]) -> dict[str, str]:
    """Pull the user's parsed attributes off `parsed_intent` into a flat
    {key: value} dict suitable for substring matching against listing
    titles. Reads both top-level fields and the `other` array of
    {key, label, value} flag rows (where the LLM stores hobby-specific
    attributes like boot_size, riding_style, ...)."""
    out: dict[str, str] = {}
    for key in _INTENT_ATTRIBUTE_KEYS:
        v = parsed_intent.get(key)
        if v is None:
            continue
        out[key] = str(v)
    other = parsed_intent.get("other")
    if isinstance(other, list):
        for row in other:
            if not isinstance(row, dict):
                continue
            k = row.get("key")
            v = row.get("value")
            if k and v not in (None, "", "null"):
                out[str(k)] = str(v)
    return out


async def _dispatch_scout_search(
    ctx: Context,
    shopping_list: dict[str, Any],
) -> dict[str, list[dict[str, Any]] | None]:
    """Fan out one Scout search per shopping-list item; gather results.

    Returns a dict keyed by item_type: list[listing] on success, [] on miss,
    None on timeout/error. Per-future timeout so one slow item doesn't
    poison the rest.
    """
    items = shopping_list.get("items") or []
    if not items:
        return {}

    hobby = shopping_list.get("hobby")
    sl_id = shopping_list.get("_id") or shopping_list.get("shopping_list_id")
    sl_budget = shopping_list.get("budget_usd")
    # User-level attributes (size, skill, style, etc.) live on the parsed
    # intent. Flatten the `other` array of {key, value} into a plain dict
    # so Scout can match them against listing titles. Skip null values.
    base_attributes = _flatten_user_attributes(
        shopping_list.get("parsed_intent") or {}
    )

    scout_addr = scout_address()
    loop = asyncio.get_event_loop()

    async def _one(item: dict[str, Any]) -> tuple[str, list[dict] | None]:
        item_type = item.get("item_type") or "item"
        request_id = uuid4().hex
        fut: asyncio.Future = loop.create_future()
        _pending[request_id] = fut

        # Use the kit's TOTAL budget as the per-item ceiling. Claude's
        # per-item allocations are tight (e.g. $30 helmet on a $300 kit),
        # which would filter out a $40 listing that's still well within
        # the user's overall budget. Scout's tiered matcher can still
        # surface near-miss listings when this cap is loose.
        if isinstance(sl_budget, (int, float)) and sl_budget > 0:
            max_price = float(sl_budget)
        else:
            max_price = float(item.get("budget_usd") or 0.0) * 2.0

        # Per-item attributes from gen_list (e.g. {style: ["all-mountain"]})
        # merge with the user-level attributes for this Scout call.
        merged_attributes = dict(base_attributes)
        for attr in item.get("attributes") or []:
            key = attr.get("key")
            values = attr.get("value") or []
            if key and values:
                first = values[0].get("value") if isinstance(values[0], dict) else None
                if first:
                    merged_attributes.setdefault(key, str(first))

        payload = {
            "op": "search",
            "request_id": request_id,
            "list_id": sl_id,
            # Per-item id (UUID generated by ShoppingListItem). Lets Scout
            # tier-1 match listings linked to this exact kit slot, not just
            # any listing with the same item_type in the same shopping list.
            "item_id": item.get("id"),
            "hobby": hobby,
            "item_type": item_type,
            "search_query": item.get("search_query"),
            "max_price": max_price or None,
            "attributes": merged_attributes or None,
            "limit": 5,
        }
        try:
            status = await send_json(ctx, scout_addr, payload)
            # uagents returns a MsgStatus on `ctx.send`. Surface non-delivered
            # status so we never time out without knowing the send itself failed.
            if status is not None and getattr(status, "status", None) not in {
                None, "delivered", "sent", "ok",
            }:
                ctx.logger.warning(
                    f"[scout dispatch] send status={status} item_type={item_type}"
                )
            reply = await asyncio.wait_for(fut, timeout=_SCOUT_TIMEOUT_S)
            return item_type, reply.get("listings") or []
        except asyncio.TimeoutError:
            ctx.logger.warning(f"[scout] timeout for item_type={item_type}")
            return item_type, None
        except Exception as exc:  # noqa: BLE001
            ctx.logger.exception(f"[scout] dispatch error: {exc}")
            return item_type, None
        finally:
            _pending.pop(request_id, None)

    pairs = await asyncio.gather(*[_one(it) for it in items])
    return dict(pairs)


async def _dispatch_pricer_score(
    ctx: Context,
    hobby: str | None,
    listings_by_item: dict[str, list[dict[str, Any]] | None],
    user_attributes: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]] | None]:
    """Send all Scout-returned listings to Pricer in a single batch.

    Returns the same dict shape, but each listing dict is enriched with
    `deal_score`, `label`, `pct_below_median`, and `median_price_usd`.
    On Pricer timeout/error, returns the input unchanged so the user
    still sees the listings, just without deal tags.
    """
    flat: list[dict[str, Any]] = []
    indexes: list[tuple[str, int]] = []  # (item_type, position) for re-merge
    for item_type, listings in listings_by_item.items():
        if not listings:
            continue
        for pos, lst in enumerate(listings):
            payload = dict(lst)
            payload.setdefault("hobby", hobby)
            payload.setdefault("item_type", item_type)
            flat.append(payload)
            indexes.append((item_type, pos))

    if not flat:
        return listings_by_item

    request_id = uuid4().hex
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    _pending[request_id] = fut

    try:
        await send_json(
            ctx,
            pricer_address(),
            {
                "op": "score",
                "request_id": request_id,
                "hobby": hobby,
                "user_attributes": user_attributes or {},
                "listings": flat,
            },
        )
        reply = await asyncio.wait_for(fut, timeout=_PRICER_TIMEOUT_S)
    except asyncio.TimeoutError:
        ctx.logger.warning(f"[pricer] timeout req={request_id}")
        return listings_by_item
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[pricer] dispatch error: {exc}")
        return listings_by_item
    finally:
        _pending.pop(request_id, None)

    scored = reply.get("scored") or []
    if len(scored) != len(indexes):
        ctx.logger.warning(
            f"[pricer] reply size mismatch: got {len(scored)} expected {len(indexes)}"
        )
    # Merge scores back into the per-item buckets in place.
    enriched = {k: list(v) if v else v for k, v in listings_by_item.items()}
    for (item_type, pos), payload in zip(indexes, scored):
        bucket = enriched.get(item_type)
        if bucket and pos < len(bucket):
            bucket[pos] = {**bucket[pos], **payload}
    return enriched


async def _initiate_payment(ctx: Context, sender: str, sess) -> None:
    """Kick off the Payment Protocol cycle by asking PaymentSink (seller)
    to send us a RequestPayment.

    In the Payment Protocol the seller initiates RequestPayment, so the
    buyer (us) can't unilaterally jump-start the cycle with that message
    type. We bootstrap with a small `init_payment` chat op carrying the
    reference; PaymentSink replies with the canonical RequestPayment, and
    we run the protocol from there.
    """
    reference = f"refresh-{sess.shopping_list_id}-{uuid4().hex[:8]}"
    sess.payment_reference = reference
    _payment_user_by_ref[reference] = sender

    sink = payment_sink_address()
    ctx.logger.info(
        f"[payment] init_payment → sink={sink[:14]}… ref={reference} "
        f"amount={_PAYMENT_AMOUNT_FET} FET"
    )
    await send_json(
        ctx,
        sink,
        {
            "op": "init_payment",
            "reference": reference,
            "amount": _PAYMENT_AMOUNT_FET,
            "currency": "FET",
            "description": "Fresh OfferUp scrape for the Hobbyist kit",
            "list_id": sess.shopping_list_id,
        },
    )


# Two correlation maps so multiple payments in flight don't cross-pollinate.
# `_payment_user_by_ref`: ref → user sender, populated when Coordinator
#   triggers the cycle, consumed when RequestPayment lands.
# `_tx_to_user`: tx_id → user sender, populated when we mint the
#   CommitPayment, consumed when CompletePayment lands.
_payment_user_by_ref: dict[str, str] = {}
_tx_to_user: dict[str, str] = {}


async def _kit_and_listings_reply(
    ctx: Context, sender: str, shopping_list: dict[str, Any]
) -> None:
    """Background task: Scout fan-out → Pricer score → final kit message.

    Runs *after* the user-message handler has returned so neither Scout's
    nor Pricer's replies queue behind it (uagents serializes inbound
    handlers per agent). Failures degrade gracefully: Scout failure
    yields the kit alone; Pricer failure yields kit + listings without
    deal tags.
    """
    try:
        listings_by_item = await _dispatch_scout_search(ctx, shopping_list)
        user_attrs = _flatten_user_attributes(
            shopping_list.get("parsed_intent") or {}
        )
        listings_by_item = await _dispatch_pricer_score(
            ctx, shopping_list.get("hobby"), listings_by_item, user_attrs
        )
        text = format_kit_with_listings(shopping_list, listings_by_item)
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[bg] dispatch error: {exc}")
        text = flatten_kit_for_chat(shopping_list)
    try:
        await ctx.send(sender, make_text_message(text))
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[bg] send error: {exc}")


def _route_agent_reply(ctx: Context, source: str, text: str) -> bool:
    """If `text` is a Scout/Pricer op-reply, resolve the matching pending future.

    `source` is one of {"scout", "pricer"} — used only for log labels.
    Returns True when handled, False to fall through to the user state machine.
    """
    op_msg = parse_json_op(text)
    if op_msg is None:
        return False
    op = op_msg.get("op")
    if op not in {"search_result", "search_error", "score_result", "score_error"}:
        return False
    request_id = op_msg.get("request_id")
    fut = _pending.get(request_id)
    if fut is None or fut.done():
        ctx.logger.warning(f"[{source} reply] no pending future for req={request_id}")
        return True

    if op == "search_error":
        ctx.logger.warning(
            f"[scout reply] error req={request_id} item_type={op_msg.get('item_type', '?')} "
            f"err={op_msg.get('error')!r}"
        )
        fut.set_result({"listings": []})
    elif op == "search_result":
        hits = len(op_msg.get("listings") or [])
        ctx.logger.info(
            f"[scout reply] ok req={request_id} "
            f"item_type={op_msg.get('item_type', '?')} hits={hits}"
        )
        fut.set_result(op_msg)
    elif op == "score_error":
        ctx.logger.warning(
            f"[pricer reply] error req={request_id} err={op_msg.get('error')!r}"
        )
        fut.set_result({"scored": []})
    else:  # score_result
        n = len(op_msg.get("scored") or [])
        ctx.logger.info(f"[pricer reply] ok req={request_id} scored={n}")
        fut.set_result(op_msg)
    return True


_LIVE_SCRAPE_TRIGGERS = {
    "go live",
    "scrape now",
    "fresh listings",
    "fresh data",
    "pay",
    "find new ones",
    "live search",
    "scrape",
}


_HELP_TEXT = (
    "Hobbyist commands:\n"
    "  • Tell me a hobby + budget + city to start a kit (e.g. 'I want to "
    "get into snowboarding, $300, in LA').\n"
    "  • After your kit lands: 'go live' to pay 0.5 FET for a fresh "
    "scrape via the Payment Protocol.\n"
    "  • 'reset' — start a new query.\n"
    "  • 'help' — show this message."
)


async def _handle_user_message(ctx: Context, sender: str, user_text: str) -> str:
    """Run one turn of the intake → kit state machine. Returns the reply text."""
    sess = sessions.get(sender)
    lowered = user_text.strip().lower()

    if lowered in {"help", "/help"}:
        return _HELP_TEXT

    # Reset hook for testing — lets you start over without losing the agent.
    if lowered in {"reset", "/reset", "start over"}:
        sessions.reset(sender)
        return (
            "Reset. Tell me about the hobby you want to get into and your "
            "budget — e.g. 'I want to start snowboarding, $300, in LA'. "
            "Type 'help' for commands."
        )

    # Payment trigger: only meaningful once a kit has been built.
    if any(trigger in lowered for trigger in _LIVE_SCRAPE_TRIGGERS):
        if sess.shopping_list_id is None:
            return (
                "I need to build your kit first. Tell me a hobby + budget "
                "(e.g. 'snowboarding $300 in LA') and I'll come back with "
                "listings. Then say 'go live' to pay for fresh data."
            )
        await _initiate_payment(ctx, sender, sess)
        return (
            f"Sent a {_PAYMENT_AMOUNT_FET} FET RequestPayment to the "
            "Hobbyist Payment Sink. Waiting for CommitPayment — fresh "
            "listings will land here once the cycle completes."
        )

    if sess.query_id is None:
        ctx.logger.info(f"[start_query] sender={sender[:14]}… text={user_text!r}")
        result = await start_query(user_text)
        sess.query_id = result["query_id"]
        return format_followup_questions(result.get("followup_questions") or [])

    if sess.shopping_list_id is None:
        ctx.logger.info(
            f"[finish_query] sender={sender[:14]}… "
            f"query_id={sess.query_id} text={user_text!r}"
        )
        result = await finish_query(sess.query_id, user_text)
        if result.get("done"):
            sess.shopping_list_id = result.get("shopping_list_id")
            shopping_list = result.get("shopping_list") or {}
            shopping_list.setdefault("shopping_list_id", sess.shopping_list_id)
            # Carry parsed_intent on the shopping_list dict so dispatch
            # sees user attributes (boot size, skill, riding style, ...).
            # Cache on session too so the post-payment refresh keeps them.
            parsed_intent = result.get("parsed_intent") or {}
            shopping_list["parsed_intent"] = parsed_intent
            sess.parsed_intent = parsed_intent
            ctx.logger.info(
                f"[scout fanout] spawning background search for "
                f"shopping_list_id={sess.shopping_list_id}"
            )
            # Run Scout dispatch as a background task. uagents serializes
            # inbound handlers per agent — if we awaited Scout's replies
            # here, they'd queue behind THIS handler and deadlock. Returning
            # immediately frees on_chat so Scout's replies can be routed,
            # then the background task sends the final kit reply.
            asyncio.create_task(
                _kit_and_listings_reply(ctx, sender, shopping_list)
            )
            hobby = shopping_list.get("hobby") or "kit"
            return (
                f"Building your {hobby} kit and searching live listings — "
                "I'll send the results in a moment."
            )
        return format_followup_questions(result.get("followup_questions") or [])

    # Kit already built. Pricer scoring + live scrape land in later phases.
    return (
        "Your kit is built. Pricer scoring and live scrape land in later phases — "
        "say 'reset' to start a new query."
    )


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    # Chat Protocol requires acknowledging every inbound message.
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )

    raw_text = extract_text(msg).strip()

    # Inter-agent reply path: Scout/Pricer send JSON op messages with the
    # request_id we issued. Resolve the pending future and stop — no user
    # reply to send for this branch.
    try:
        if sender == scout_address() and _route_agent_reply(ctx, "scout", raw_text):
            return
    except RuntimeError:
        pass  # SCOUT_SEED missing — fall through.
    try:
        if sender == pricer_address() and _route_agent_reply(ctx, "pricer", raw_text):
            return
    except RuntimeError:
        pass  # PRICER_SEED missing — fall through.

    # ASI:One prepends the recipient's @-handle to every chat — strip it
    # so the intent parser sees a clean intent.
    text = strip_agent_handle(raw_text).strip()
    ctx.logger.info(f"[chat] from {sender[:14]}…: {text!r}")
    if not text:
        await ctx.send(sender, make_text_message("(empty message — say something)"))
        return

    try:
        reply = await _handle_user_message(ctx, sender, text)
    except Exception as exc:
        # Don't let a Mongo / LLM hiccup crash the handler — the protocol
        # state would desync and the agent would look dead in ASI:One.
        ctx.logger.exception(f"handler error: {exc}")
        reply = f"Something went wrong on my end ({type(exc).__name__}). Try 'reset' to start over."

    await ctx.send(sender, make_text_message(reply))


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    # Required by Chat Protocol but otherwise no-op for now.
    pass


# Buyer role's locked _models in the spec are exactly the messages the
# buyer is supposed to handle: RequestPayment, CompletePayment, CancelPayment.
# Register handlers via the protocol so spec verification passes.


@payment_proto.on_message(RequestPayment)
async def on_request_payment(
    ctx: Context, sender: str, msg: RequestPayment
) -> None:
    """Seller is asking us to pay. Generate a mock testnet transaction_id
    and reply with CommitPayment. (Real settlement would hit the FET
    ledger here — for the demo the protocol message exchange is what's
    scored, not actual on-chain transfer.)"""
    funds = msg.accepted_funds[0] if msg.accepted_funds else Funds(
        amount=_PAYMENT_AMOUNT_FET, currency="FET", payment_method="testnet"
    )
    tx_id = f"TESTNET-{uuid4().hex[:16].upper()}"
    # Carry the user mapping forward: when the seller eventually replies
    # with CompletePayment(transaction_id), we need to know which user
    # triggered the cycle. The reference came in via init_payment.
    user_sender = _payment_user_by_ref.pop(msg.reference or "", None)
    if user_sender is not None:
        _tx_to_user[tx_id] = user_sender
    ctx.logger.info(
        f"[payment] RequestPayment from {sender[:14]}…: "
        f"amount={funds.amount} {funds.currency} ref={msg.reference!r} "
        f"→ committing tx={tx_id}"
    )
    await ctx.send(
        sender,
        CommitPayment(
            funds=Funds(
                amount=funds.amount,
                currency=funds.currency,
                payment_method=funds.payment_method or "testnet",
            ),
            recipient=msg.recipient,
            transaction_id=tx_id,
            reference=msg.reference,
            description=msg.description,
            metadata=msg.metadata,
        ),
    )


@payment_proto.on_message(CompletePayment)
async def on_complete_payment(
    ctx: Context, sender: str, msg: CompletePayment
) -> None:
    """Seller confirmed our payment landed. Resume the user's kit flow
    with a fresh Scout fan-out (gated content unlocked)."""
    tx_id = msg.transaction_id or "?"
    ctx.logger.info(
        f"[payment] CompletePayment from {sender[:14]}…: tx={tx_id}"
    )
    # The reference travels through the Payment Protocol, but
    # CompletePayment in this spec only carries transaction_id. The
    # transaction_id we generated is unique per request, so use it as the
    # correlation key — we kept the mapping in `_tx_to_user`.
    user_sender = _tx_to_user.pop(tx_id, None)
    if user_sender is None:
        ctx.logger.warning(
            f"[payment] no user mapped to tx {tx_id!r} — dropping refresh"
        )
        return

    sess = sessions.get(user_sender)
    sess.payment_committed = True
    sess.payment_reference = None

    if not sess.shopping_list_id:
        await ctx.send(
            user_sender,
            make_text_message(
                f"Payment confirmed (tx {tx_id}) but I no longer have your "
                "kit on file — say 'reset' and start over."
            ),
        )
        return

    shopping_list = await fetch_shopping_list(sess.shopping_list_id) or {}
    shopping_list.setdefault("shopping_list_id", sess.shopping_list_id)
    if sess.parsed_intent:
        shopping_list["parsed_intent"] = sess.parsed_intent
    asyncio.create_task(
        _refreshed_kit_reply(ctx, user_sender, shopping_list, tx_id)
    )


@payment_proto.on_message(CancelPayment)
async def on_cancel_payment(
    ctx: Context, sender: str, msg: CancelPayment
) -> None:
    ctx.logger.warning(
        f"[payment] CancelPayment from {sender[:14]}…: reason={getattr(msg, 'reason', None)!r}"
    )


_LIVE_SCRAPE_POLL_S = 5.0
_LIVE_SCRAPE_TIMEOUT_S = 150.0  # 30 polls × 5s = 2.5 min hard cap


async def _run_live_scrape(ctx: Context, shopping_list_id: str) -> str:
    """Trigger listing_search.start_search and poll until it finishes.

    Lazy-imports `listing_search` so a missing Playwright install doesn't
    break agent startup. Returns a status string suitable for logging.
    """
    try:
        from backend.services.listing_search import (
            get_search_status,
            start_search,
        )
    except Exception as exc:  # noqa: BLE001
        ctx.logger.warning(f"[scrape] listing_search unavailable: {exc}")
        return "skipped"

    try:
        await start_search(shopping_list_id)
    except ValueError as exc:
        # "Another search is in progress" — fine, fall through to polling.
        ctx.logger.info(f"[scrape] start_search: {exc}")
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[scrape] start_search error: {exc}")
        return "error"

    elapsed = 0.0
    last_done = 0
    while elapsed < _LIVE_SCRAPE_TIMEOUT_S:
        await asyncio.sleep(_LIVE_SCRAPE_POLL_S)
        elapsed += _LIVE_SCRAPE_POLL_S
        try:
            status = await get_search_status(shopping_list_id)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning(f"[scrape] get_search_status error: {exc}")
            return "poll_error"
        if status is None:
            continue
        s = status.get("status")
        done = status.get("items_done", 0)
        if done != last_done:
            ctx.logger.info(
                f"[scrape] {shopping_list_id} {done}/{status.get('items_total','?')} items"
            )
            last_done = done
        if s in {"done", "error"}:
            ctx.logger.info(
                f"[scrape] {shopping_list_id} finished status={s} "
                f"counts={status.get('counts', {})}"
            )
            return s
    ctx.logger.warning(f"[scrape] {shopping_list_id} timed out after {elapsed:.0f}s")
    return "timeout"


async def _refreshed_kit_reply(
    ctx: Context,
    sender: str,
    shopping_list: dict[str, Any],
    transaction_id: str,
) -> None:
    """Background: trigger live OfferUp scrape, then re-run Scout/Pricer
    with the fresh listings and send the user the new kit message.

    Live scrape is best-effort — if it fails or times out, we still run
    Scout against whatever's already in Mongo so the user always gets a
    reply. The Payment Protocol cycle has already settled by this point;
    rubric credit is locked in regardless of scrape outcome.
    """
    sl_id = shopping_list.get("shopping_list_id")
    if sl_id:
        try:
            await ctx.send(
                sender,
                make_text_message(
                    f"Payment confirmed (testnet tx {transaction_id}). "
                    "Triggering a live OfferUp scrape now — fresh listings in 30-90s…"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            ctx.logger.exception(f"[payment refresh] interim send: {exc}")
        scrape_status = await _run_live_scrape(ctx, sl_id)
        ctx.logger.info(f"[payment refresh] scrape outcome: {scrape_status}")

    try:
        listings_by_item = await _dispatch_scout_search(ctx, shopping_list)
        user_attrs = _flatten_user_attributes(
            shopping_list.get("parsed_intent") or {}
        )
        listings_by_item = await _dispatch_pricer_score(
            ctx, shopping_list.get("hobby"), listings_by_item, user_attrs
        )
        body = format_kit_with_listings(shopping_list, listings_by_item)
        text = (
            f"Fresh results (tx {transaction_id}):\n\n{body}"
        )
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[payment refresh] dispatch error: {exc}")
        text = (
            f"Payment confirmed (tx {transaction_id}) but the fresh search "
            "ran into an issue. Try 'go live' again."
        )
    try:
        await ctx.send(sender, make_text_message(text))
    except Exception as exc:  # noqa: BLE001
        ctx.logger.exception(f"[payment refresh] send error: {exc}")


agent.include(chat_proto, publish_manifest=True)
agent.include(payment_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()
