# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A buyer-side AI agent for hobbyists. The user types a natural-language intent like *"I want to get into snowboarding, budget $300, in LA"*, and the agent returns a curated kit of real secondhand listings within budget.

LA Hacks 2026 hackathon project.

## Repo layout

```
backend/                       # Python backend (services + LLM prompts)
  __init__.py                  # calls load_dotenv() on import
  prompts/
    intent_parser.txt          # system prompt for the intent parser
    followup.txt               # empty stub from teammate
  services/
    intent_parser.py           # parse_intent(text, skeleton) -> dict
    gen_followup.py            # generate follow-up questions + hobby-specific flags
    gen_list.py                # generate shopping list JSON from completed intent
    query_flow.py              # Mongo-backed prompt/follow-up/shopping-list lifecycle
    listing_store.py           # normalize/upsert scraper output into listings

backend/kitscout/              # MongoDB Atlas data layer
  db.py                        # AsyncIOMotorClient + collection refs (queries, shopping_lists, listings)
  schemas.py                   # Pydantic v2 models: Query, ShoppingList, Listing, Location
  indexes.py                   # ensure_indexes() for the three active collections

frontend/                      # Vite + React (teammate)

tests/
  test_parser.py               # 1 schema test + 6 live-API tests (@pytest.mark.integration)
  test_db.py                   # 3 schema tests + 3 mongo round-trip tests (@pytest.mark.mongo)

seed_db.py                     # populates 1 query + 1 shopping_list + sample listings
.env / .env.example            # ANTHROPIC_API_KEY, MONGODB_URI
pyproject.toml                 # editable install + pytest markers; dynamic deps from requirements.txt
requirements.txt               # runtime deps (single source of truth)
```

## Stack — current

- **Python 3.11+**, type hints on every function
- **Anthropic Claude Haiku 4.5** via `client.messages.parse(output_format=PydanticClass)` for structured intent parsing
- **MongoDB Atlas** via **motor** (async driver). `tlsCAFile=certifi.where()` is required because of how python.org Python on macOS handles certificates.
- **Pydantic v2** for every cross-module data structure
- **Frontend**: Vite + React (teammate's `frontend/`)

## Architecture — planned vs done

```
User input
   │
   ▼
create_query_session() ─▶ parse_intent() ─▶ Claude
   │  (DONE)              (DONE)
   ▼
queries collection ──────────────────┐
                                     │ parsed intent + follow-up flags
                                     ▼
complete_query_session() ─▶ gen_list() ──▶ shopping_lists collection
                                     │
                                     ▼
listing_store          ──▶ scraper output ──▶ listings collection
```

**Done:**
- Intent parser (text + skeleton → dict)
- DB layer (3 collections: `queries`, `shopping_lists`, `listings`)
- Query flow service stores parsed queries, follow-ups, and generated shopping lists
- Listing store service links scraper output back to shopping list item searches
- Sample data (`seed_db.py`)
- Tests with cleanup (no leftover data on cluster)

**Not done — likely next steps:**
- API surface for frontend calls
- Search orchestration: call scraper from shopping list item `search_query` values
- Ranking/selection logic over `listings` for each shopping list item
- API surface: a uAgent or HTTP endpoint that the frontend can call
- Frontend ↔ backend wiring

## Commands

```bash
# Setup (once)
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"        # OR: .venv/bin/pip install -r requirements.txt
cp .env.example .env                      # then fill in ANTHROPIC_API_KEY and MONGODB_URI

# Run the parser on a single query (single-quote queries with $ to avoid shell expansion!)
.venv/bin/python -m backend.services.intent_parser 'i want to snowboard for under $250'

# Populate sample data (wipes + reseeds the 3 active collections)
.venv/bin/python seed_db.py

# Run all tests (skips integration/mongo tests if env vars aren't set)
.venv/bin/pytest tests/ -v
```

## Conventions

- **Type hints** on every function signature.
- **Pydantic v2** for any data structure that crosses a module boundary.
- **Async everywhere** for db access (motor is async; uAgents handlers are async).
- **Don't create your own MongoClient.** Always import from `backend.kitscout.db`. The connection pool is shared per-process.
- **Service layer for db ops** — when a query is used in 2+ places, extract it into `backend/services/<name>.py` and import from there. Inline motor calls are fine for one-off operations.
- **Prompts as text files** in `backend/prompts/`, loaded at import. Tweak prompts without code changes.
- **No secrets in code.** Both API keys live in `.env`; `backend/__init__.py` and `backend/kitscout/db.py` both call `load_dotenv()`. `.env` is gitignored.

## Open decisions / coordination items

1. **`backend/services/followup.service.js` is JavaScript, all our other backend code is Python.** Resolve with teammate before adding more services. Current direction (implicit): Python backend.
2. **Originally planned around uAgents (Fetch.ai's Agentverse).** With the frontend/backend split, multi-agent on Agentverse may no longer be the right shape — confirm whether the Fetch.ai track is still being targeted.
3. **Listings source** — Craigslist / Facebook Marketplace / eBay. The schema (`Listing.fb_id`) currently assumes Facebook Marketplace. Will need adapters per source.
4. **Currency scope** — current FX rate table in `backend/prompts/intent_parser.txt` is static (April 2026). Fine for the demo. Swap for an FX API only if needed.

## Resolved decisions

- **LLM provider**: Anthropic Claude Haiku 4.5. (Switched from Opus 4.7 for cost; quality on JSON extraction is identical.)
- **DB**: MongoDB Atlas via motor (async). uAgents requires async; pymongo would block.
