"""Resolve each agent's deterministic Agentverse address from its seed.

uagents derives address-from-seed via Identity.from_seed(seed, index).
We expose lazy accessors so importing this module never crashes when
some seed is missing — only the call site that actually needs the
address sees the failure.
"""

import os
from functools import lru_cache

from uagents_core.identity import Identity


@lru_cache(maxsize=None)
def _addr_from_seed_var(seed_var: str) -> str:
    seed = os.environ.get(seed_var)
    if not seed:
        raise RuntimeError(
            f"{seed_var} not set in .env — run scripts/print_addresses.py "
            f"after seeding to verify."
        )
    return Identity.from_seed(seed, 0).address


def coordinator_address() -> str:
    return _addr_from_seed_var("COORDINATOR_SEED")


def scout_address() -> str:
    return _addr_from_seed_var("SCOUT_SEED")


def pricer_address() -> str:
    return _addr_from_seed_var("PRICER_SEED")


def payment_sink_address() -> str:
    return _addr_from_seed_var("PAYMENT_SINK_SEED")
