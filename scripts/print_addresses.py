"""Print each agent's deterministic Agentverse address from its seed.

    .venv/bin/python scripts/print_addresses.py

Use the printed addresses when filling Agentverse registration fields,
when wiring inter-agent dispatch (COORDINATOR_ADDR / SCOUT_ADDR / PRICER_ADDR),
or when debugging a "why is this message not arriving?" mystery.

Safe to run before agents are running — pure key derivation, no network.
"""

import os
import sys
from pathlib import Path

# Ensure project root + .env loadable when invoked from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from uagents_core.identity import Identity  # noqa: E402


SEED_VARS = ("COORDINATOR_SEED", "SCOUT_SEED", "PRICER_SEED", "PAYMENT_SINK_SEED")


def main() -> int:
    missing = []
    for var in SEED_VARS:
        seed = os.environ.get(var)
        if not seed:
            print(f"{var:24s}  (not set in .env)")
            missing.append(var)
            continue
        addr = Identity.from_seed(seed, 0).address
        print(f"{var:24s}  {addr}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
