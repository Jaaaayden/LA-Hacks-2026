"""Push the latest description + README for every agent up to Agentverse.

uagents only publishes an agent's profile (description, README, avatar) on
the first /connect from the Agentverse Inspector. Subsequent restarts and
description tweaks aren't auto-pushed, so the public profile pages stay
stale. This script does the push directly via Agentverse's REST API
(challenge → identity proof → register), giving us a one-shot sync any
time we change copy.

    .venv/bin/python scripts/sync_agentverse_profiles.py

Required env: AGENTVERSE_API_KEY + the four agent SEEDs.
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
os.environ.setdefault("REQUESTS_CA_BUNDLE", certifi.where())

from uagents.config import AgentverseConfig  # noqa: E402
from uagents.mailbox import (  # noqa: E402
    AgentverseConnectRequest,
    register_in_agentverse,
)
from uagents_core.identity import Identity  # noqa: E402
from uagents_core.registration import (  # noqa: E402
    AgentEndpoint,
    AgentProfile,
    RegistrationRequest,
)


# Import each agent module and pull description / readme / protocol digests
# directly off the constructed Agent. Importing constructs the Agent but
# does NOT bind a port (that only happens on .run()), so it's safe to do
# alongside a live Bureau.
def _agent_specs() -> list[dict]:
    from backend.agents.coordinator.agent import agent as coord
    from backend.agents.payment_sink.agent import agent as sink
    from backend.agents.pricer.agent import agent as pricer
    from backend.agents.scout.agent import agent as scout

    pairs = [
        ("COORDINATOR_SEED", coord),
        ("SCOUT_SEED", scout),
        ("PRICER_SEED", pricer),
        ("PAYMENT_SINK_SEED", sink),
    ]
    return [
        {
            "seed_var": seed_var,
            "name": ag.name,
            "description": ag._description or "",
            "readme": ag._readme or "",
            "protocols": list(ag.protocols.keys()),
        }
        for seed_var, ag in pairs
    ]


async def sync_one(
    api_key: str,
    spec: dict,
    agentverse: AgentverseConfig,
) -> tuple[str, bool, str | None]:
    seed = os.environ.get(spec["seed_var"])
    if not seed:
        return spec["name"], False, f"{spec['seed_var']} not set"

    identity = Identity.from_seed(seed, 0)

    profile = AgentProfile(
        description=spec["description"],
        readme=spec["readme"],
        avatar_url="",
    )

    # Mailbox-routed agents advertise the Agentverse mailbox URL as their
    # endpoint — pulled from AgentverseConfig so it tracks any future
    # path/version change.
    mailbox_endpoint = agentverse.mailbox_endpoint

    registration = RegistrationRequest(
        address=identity.address,
        name=spec["name"],
        handle=None,
        url=None,
        agent_type="mailbox",
        profile=profile,
        endpoints=[AgentEndpoint(url=mailbox_endpoint, weight=1)],
        protocols=spec["protocols"],
    )

    request = AgentverseConnectRequest(
        user_token=api_key,
        agent_type="mailbox",
        endpoint=mailbox_endpoint,
    )

    response = await register_in_agentverse(
        request=request,
        identity=identity,
        prefix="agent",
        agentverse=agentverse,
        agent_details=registration,
    )
    return spec["name"], response.success, response.detail


async def main() -> int:
    api_key = os.environ.get("AGENTVERSE_API_KEY")
    if not api_key:
        print("AGENTVERSE_API_KEY is not set in .env")
        return 1

    agentverse = AgentverseConfig()
    specs = _agent_specs()

    failures = 0
    for spec in specs:
        name, success, detail = await sync_one(api_key, spec, agentverse)
        status = "OK" if success else "FAIL"
        protos = len(spec["protocols"])
        print(f"{status:5s} {name:28s} protocols={protos}  {detail or ''}")
        if not success:
            failures += 1

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
