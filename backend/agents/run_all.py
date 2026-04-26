"""Run all Hobbyist agents in a single uagents Bureau.

Why a Bureau: when two agents live in separate processes, Coordinator → Scout
dispatch has to resolve Scout's address through Agentverse's Almanac API,
which depends on registration propagation and on-chain state we don't
maintain (no FET in our wallet). Bureau registers both agents on one
process-local resolver — sends are direct, mailbox stays on for ASI:One
inbound chats.

Run:
    .venv/bin/python -m backend.agents.run_all

Each agent keeps its own seed / address / mailbox identity. Stopping the
process stops both agents.
"""

# bootstrap MUST be first — loads .env before kitscout.db touches Mongo.
from backend.agents.common import bootstrap  # noqa: F401

from uagents import Bureau

from backend.agents.coordinator.agent import agent as coordinator_agent
from backend.agents.payment_sink.agent import agent as payment_sink_agent
from backend.agents.pricer.agent import agent as pricer_agent
from backend.agents.scout.agent import agent as scout_agent


def main() -> None:
    bureau = Bureau(
        agents=[
            coordinator_agent,
            scout_agent,
            pricer_agent,
            payment_sink_agent,
        ]
    )
    bureau.run()


if __name__ == "__main__":
    main()
