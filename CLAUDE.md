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
    intent_parser.py           # parse_intent(query) -> ParsedIntent (Claude Haiku 4.5)
    query.py                   # record_query(text) -> (ParsedIntent, query_id) — parser + db bridge
    followup.service.js        # ⚠️ JS file from teammate; backend language is unresolved

kitscout/                      # MongoDB Atlas data layer
  db.py                        # AsyncIOMotorClient + collection refs (listings, item_comps, queries, offers)
  schemas.py                   # Pydantic v2 models: Listing, ItemComp, Query, Offer, Location
  indexes.py                   # ensure_indexes() — currently: unique fb_id on listings

frontend/                      # Vite + React (teammate)

tests/
  test_parser.py               # 1 schema test + 6 live-API tests (@pytest.mark.integration)
  test_db.py                   # 3 schema tests + 3 mongo round-trip tests (@pytest.mark.mongo)

seed_db.py                     # populates 12 listings + 6 comps + 2 queries + 1 offer (across 3 hobbies)
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
record_query()  ────▶  parse_intent()  ────▶  Claude Haiku 4.5
   │  (DONE)              (DONE)
   ▼
queries collection ──────────────────┐
                                     │ ParsedIntent
                                     ▼
                              SearchAgent  ──▶  scrape FB Marketplace, etc.
                              (TODO)            ──▶  listings collection
                                     │
                                     ▼
                              Ranker     ──▶  bundle into Offer
                              (TODO)            ──▶  offers collection
                                                ──▶  link back via queries.offer_id
```

**Done:**
- Intent parser (text → `ParsedIntent`)
- DB layer (4 collections, schemas, unique-fb_id index)
- Bridge service (`record_query` writes parsed query into `queries`)
- Sample data (`seed_db.py`)
- Tests with cleanup (no leftover data on cluster)

**Not done — likely next steps:**
- SearchAgent: scrape Facebook Marketplace / Craigslist for listings, write to `listings`
- Ranker: read `listings` + `item_comps`, build curated `Offer`, link back to `queries.offer_id`
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

# Parse + store in queries collection
.venv/bin/python -m backend.services.query 'i want to snowboard for under $250'

# Populate sample data (wipes + reseeds the 4 collections)
.venv/bin/python seed_db.py

# Run all tests (skips integration/mongo tests if env vars aren't set)
.venv/bin/pytest tests/ -v
```

## Conventions

- **Type hints** on every function signature.
- **Pydantic v2** for any data structure that crosses a module boundary.
- **Async everywhere** for db access (motor is async; uAgents handlers are async).
- **Don't create your own MongoClient.** Always import from `kitscout.db`. The connection pool is shared per-process.
- **Service layer for db ops** — when a query is used in 2+ places, extract it into `backend/services/<name>.py` and import from there. Inline motor calls are fine for one-off operations.
- **Prompts as text files** in `backend/prompts/`, loaded at import. Tweak prompts without code changes.
- **No secrets in code.** Both API keys live in `.env`; `backend/__init__.py` and `kitscout/db.py` both call `load_dotenv()`. `.env` is gitignored.

## Open decisions / coordination items

1. **`backend/services/followup.service.js` is JavaScript, all our other backend code is Python.** Resolve with teammate before adding more services. Current direction (implicit): Python backend.
2. **Originally planned around uAgents (Fetch.ai's Agentverse).** With the frontend/backend split, multi-agent on Agentverse may no longer be the right shape — confirm whether the Fetch.ai track is still being targeted.
3. **Listings source** — Craigslist / Facebook Marketplace / eBay. The schema (`Listing.fb_id`) currently assumes Facebook Marketplace. Will need adapters per source.
4. **Currency scope** — current FX rate table in `backend/prompts/intent_parser.txt` is static (April 2026). Fine for the demo. Swap for an FX API only if needed.

## Resolved decisions

- **LLM provider**: Anthropic Claude Haiku 4.5. (Switched from Opus 4.7 for cost; quality on JSON extraction is identical.)
- **DB**: MongoDB Atlas via motor (async). uAgents requires async; pymongo would block.
