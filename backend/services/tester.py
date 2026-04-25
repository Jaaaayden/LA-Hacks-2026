"""
End-to-end smoke test: intent parser (custom NL + inline skeleton) -> gen_followup.

Run from repo root:
  .venv\\Scripts\\python.exe -m backend.services.tester
Optional: pass the user message as argv (use single quotes in PowerShell if it contains $).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from backend.services.gen_followup import gen_followup
from backend.services.intent_parser import parse_intent

# Natural-language query the parser fills from (edit freely).
CUSTOM_USER_MESSAGE = (
    "I want to snowboard, maybe $400 max"
)

# Intent template the model must fill (same keys as tool output; raw_query is added by parse_intent).
SKELETON: dict[str, Any] = {
    "hobby": None,
    "budget_usd": None,
    "location": None,
    "skill_level": None,
    "other": None,
}

INCLUDE_HOBBY_OTHER_FLAGS = True


def main() -> None:
    text = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else CUSTOM_USER_MESSAGE
    intent = parse_intent(text, SKELETON)
    merged_for_db: dict[str, Any] = {}
    out = gen_followup(
        intent,
        include_hobby_other_flags=INCLUDE_HOBBY_OTHER_FLAGS,
        merged_intent_out=merged_for_db,
    )
    print(
        json.dumps(
            {
                "parsed_intent": intent,
                "gen_followup": out,
                "merged_intent_for_db": merged_for_db,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
