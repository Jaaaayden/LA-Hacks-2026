"""Hobbyist Payment Sink — mock seller for the Payment Protocol cycle.

The Fetch.ai track values the optional Payment Protocol. To demo the full
RequestPayment → CommitPayment → CompletePayment exchange we need a
counterparty that auto-runs the seller side. This agent does exactly that
and nothing else.

Sequence:
  1. Coordinator (buyer) sends a chat msg with op="init_payment" + ref
  2. PaymentSink (seller) sends RequestPayment back to Coordinator
  3. Coordinator replies with CommitPayment (mock testnet tx_id)
  4. PaymentSink replies with CompletePayment

Run:
    .venv/bin/python -m backend.agents.payment_sink.agent

Required env: PAYMENT_SINK_SEED, AGENTVERSE_API_KEY.
"""

# bootstrap MUST be first — loads .env before downstream modules.
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
from uagents_core.contrib.protocols.payment import (
    CommitPayment,
    CompletePayment,
    Funds,
    RejectPayment,
    RequestPayment,
    payment_protocol_spec,
)

from backend.agents.common.messaging import (
    extract_text,
    make_text_message,
    parse_json_op,
    strip_agent_handle,
)


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


agent = Agent(
    name="hobbyist-payment-sink",
    seed=_require_env("PAYMENT_SINK_SEED"),
    port=8004,
    mailbox=True,
    publish_agent_details=True,
    readme_path=_README_PATH,
    description=(
        "Hobbyist Payment Sink — demo Marketplace fulfillment endpoint "
        "for the Payment Protocol cycle. On an init_payment trigger from "
        "the Hobbyist Coordinator it sends RequestPayment, accepts the "
        "buyer's CommitPayment, and replies with CompletePayment. "
        "Demonstration only; no real on-chain settlement."
    ),
)


# Seller-role payment protocol — handles inbound CommitPayment, RejectPayment.
payment_proto = Protocol(spec=payment_protocol_spec, role="seller")
chat_proto = Protocol(spec=chat_protocol_spec)


_HELP_TEXT = (
    "Hi! I'm Hobbyist Payment Sink — a demo seller agent that runs the "
    "Payment Protocol cycle on behalf of the Hobbyist Coordinator. The "
    "Coordinator triggers me with an init_payment chat op and I respond "
    "with a RequestPayment, accept the buyer's CommitPayment, and send "
    "back a CompletePayment. Mock testnet only — no real settlement."
)


@chat_proto.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage) -> None:
    """Coordinator initiates the cycle via this chat op. Direct human
    pings get the help text instead."""
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )
    text = strip_agent_handle(extract_text(msg).strip()).strip()
    ctx.logger.info(f"[payment-sink chat] from {sender[:14]}…: {text[:120]!r}")

    op_msg = parse_json_op(text)
    if op_msg is None or op_msg.get("op") != "init_payment":
        await ctx.send(sender, make_text_message(_HELP_TEXT))
        return

    reference = str(op_msg.get("reference") or "")
    amount = str(op_msg.get("amount") or "0.5")
    currency = str(op_msg.get("currency") or "FET")
    description = str(op_msg.get("description") or "Hobbyist scrape unlock")

    ctx.logger.info(
        f"[payment-sink] init_payment ref={reference!r} → sending "
        f"RequestPayment {amount} {currency}"
    )
    await ctx.send(
        sender,
        RequestPayment(
            accepted_funds=[
                Funds(amount=amount, currency=currency, payment_method="testnet"),
            ],
            recipient=ctx.agent.address,
            deadline_seconds=120,
            reference=reference,
            description=description,
            metadata={
                "list_id": str(
                    op_msg.get("list_id") or op_msg.get("shopping_list_id") or ""
                ),
            },
        ),
    )


@chat_proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    pass


@payment_proto.on_message(CommitPayment)
async def on_commit_payment(
    ctx: Context, sender: str, msg: CommitPayment
) -> None:
    """Buyer committed payment — log it and confirm with CompletePayment."""
    ctx.logger.info(
        f"[payment-sink] CommitPayment from {sender[:14]}…: "
        f"tx={msg.transaction_id} ref={msg.reference!r} → "
        "sending CompletePayment"
    )
    await ctx.send(
        sender, CompletePayment(transaction_id=msg.transaction_id)
    )


@payment_proto.on_message(RejectPayment)
async def on_reject_payment(
    ctx: Context, sender: str, msg: RejectPayment
) -> None:
    ctx.logger.warning(
        f"[payment-sink] RejectPayment from {sender[:14]}…: "
        f"reason={msg.reason!r}"
    )


agent.include(chat_proto, publish_manifest=True)
agent.include(payment_proto, publish_manifest=True)


if __name__ == "__main__":
    agent.run()
