# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A buyer-side AI agent for hobbyists. The user types a natural-language intent like *"I want to get into snowboarding, budget $300, in LA"*, and the agent returns a curated kit of real secondhand listings within budget.

LA Hacks 2026 hackathon project. Originally planned around Fetch.ai's Agentverse / uAgents (see "Open decisions" — that part is no longer locked in now that there's a separate `frontend/` and `backend/` split).

## Repo layout

```
backend/
  prompts/
    intent_parser.txt            # system prompt for the intent parser (plain text, hand-edited)
  services/
    intent_parser.py             # ParsedIntent schema + parse_intent() — calls Claude via messages.parse()
    followup.service.js          # ⚠️ JS file from teammate's commit — needs alignment, see below
  prompts/
    followup.txt                 # empty stub from teammate's commit
frontend/                        # Vite + React (teammate)
  src/App.jsx, ...
tests/
  test_parser.py                 # 1 schema test + 6 integration tests for parse_intent
.env                             # ANTHROPIC_API_KEY (gitignored)
.env.example                     # template
pyproject.toml                   # Python deps + pytest config
```

**`backend/__init__.py` calls `load_dotenv()`** so any caller that imports from `backend.*` gets `.env` loaded automatically.

## Stack — current

- **Python 3.11+**, type hints on every function
- **Anthropic Claude** via the `anthropic` SDK — `client.messages.parse(..., output_format=PydanticClass)` gives validated structured output
- **Pydantic v2** — all cross-module schemas
- **Frontend**: Vite + React (teammate's `frontend/`)
- **Model**: `claude-opus-4-7` (set in `backend/services/intent_parser.py`). Switch to `claude-haiku-4-5` for cheaper inference if cost matters; the structured-output API is identical.

## Component: Intent Parser (DONE for v1)

Located at `backend/services/intent_parser.py`. Public surface:

```python
from backend.services.intent_parser import parse_intent, ParsedIntent

intent: ParsedIntent = parse_intent("i want to snowboard for under $250")
```

### Schema (current, v1 minimal)

```python
class UserDetails(BaseModel):
    age: int | None = None
    occupation: str | None = None
    constraints: list[str] | None = None

class ParsedIntent(BaseModel):
    hobby: str | None = None
    budget_usd: float | None = None
    location: str | None = None
    skill_level: Literal["beginner", "intermediate", "advanced"] | None = None
    user_details: UserDetails = Field(default_factory=UserDetails)
    raw_query: str                                 # set by parse_intent, not by the LLM
```

Fixed shape, missing values are `null`. Internally the LLM is given the schema *without* `raw_query` (it's added afterward) so we don't waste tokens echoing the query back.

### Things deliberately NOT in v1

These were in the original plan; we shipped without them. Add only if a downstream component proves it needs them:

- `hobby_specifics` open dict (per-hobby gear attributes)
- `missing_fields` list
- `confidence` self-rating
- Clarification loop — caller currently checks `intent.hobby is None` etc. and asks the user themselves

### Prompt strategy

System prompt lives in `backend/prompts/intent_parser.txt` (loaded at module import). Tells the LLM to:
- Normalize `hobby` to lowercase canonical form
- Convert currency to USD using a static rate table (no FX API call)
- Map skill cues to the three-level enum
- Fill `user_details.*` only when explicitly mentioned, null otherwise
- Never guess — null is correct when info is absent

## Conventions

- **Type hints** on every function signature.
- **Pydantic** for any data structure that crosses a module boundary.
- **No secrets in code.** API keys live in `.env`; `backend/__init__.py` loads it. `.env` is in `.gitignore`.
- **Prompts as text files** under `backend/prompts/` (matches teammate's pattern), not inline strings. Lets you tweak the prompt without touching code.

## Commands

```bash
# Setup (once)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
cp .env.example .env  # then edit to add ANTHROPIC_API_KEY

# Run the parser on a single query (single-quote queries with $ to avoid shell expansion!)
.venv/bin/python -m backend.services.intent_parser 'i want to snowboard for under $250'

# Run all tests (skips integration tests if ANTHROPIC_API_KEY isn't set)
.venv/bin/pytest tests/ -v

# Run only the schema test (no API key required)
.venv/bin/pytest tests/test_parser.py::test_schema_defaults
```

## Open decisions / coordination items

1. **`backend/services/followup.service.js` is JavaScript** — but our parser is Python. Either the teammate's backend will be Node/Express (in which case `intent_parser.py` doesn't fit and we need to rewrite or expose it via a service boundary), or the `.js` was a placeholder and the whole backend should be Python. **Resolve with teammate before adding more components.**
2. **Originally planned around uAgents (Fetch.ai)** — with a frontend/backend split now in place, the multi-agent Agentverse pattern may no longer be the right shape. Confirm whether the Fetch.ai track is still being targeted.
3. **Listings source** — Craigslist / Facebook Marketplace / eBay. Affects what `user_details.constraints` and any future `hobby_specifics` keys are actually useful for.
4. **Currency scope** — current rate table is static (April 2026); USD is the canonical output. Fine for the demo. If we need accuracy beyond a few weeks, swap in an FX API.
