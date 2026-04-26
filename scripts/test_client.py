"""One-shot test client: sends a ChatMessage to the Coordinator and prints the reply.

Usage:
    .venv/bin/python scripts/test_client.py

Run this WHILE the Coordinator is running in another terminal.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from datetime import datetime, timezone
from uuid import uuid4

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    TextContent,
    chat_protocol_spec,
)


COORDINATOR_ADDR = (
    "agent1q0z45xyfa23mtk5esjas99yd20qwd2vnun9d4qk55z5s9hcasss8q7g9394"
)


client = Agent(
    name="hobbyist-test-client",
    seed="test-client-fixed-seed-123-do-not-share-publicly",
    port=8011,
    mailbox=True,
)

proto = Protocol(spec=chat_protocol_spec)


@proto.on_message(ChatMessage)
async def on_reply(ctx: Context, sender: str, msg: ChatMessage) -> None:
    text = "".join(c.text for c in msg.content if isinstance(c, TextContent))
    ctx.logger.info(f"GOT REPLY from {sender[:18]}...: {text!r}")
    await ctx.send(
        sender,
        ChatAcknowledgement(
            timestamp=datetime.now(timezone.utc),
            acknowledged_msg_id=msg.msg_id,
        ),
    )


@proto.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
    ctx.logger.info(f"got ack from {sender[:18]}...")


@client.on_event("startup")
async def send_test_msg(ctx: Context) -> None:
    msg = ChatMessage(
        timestamp=datetime.now(timezone.utc),
        msg_id=uuid4(),
        content=[TextContent(type="text", text="hello from test client")],
    )
    ctx.logger.info("SENDING 'hello from test client' to coordinator...")
    await ctx.send(COORDINATOR_ADDR, msg)


client.include(proto, publish_manifest=True)


if __name__ == "__main__":
    client.run()
