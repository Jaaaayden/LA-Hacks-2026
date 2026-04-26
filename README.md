# Hobbyist — a multi-agent buyer-side AI for hobbyists

> *"I want to get into snowboarding, $300, in LA"* → a curated kit of real used-marketplace listings, scored against the median price, with on-demand fresh-scrape unlocks gated by the Fetch.ai Payment Protocol.

LA Hacks 2026 — Fetch.ai Agentverse track ("Search & Discovery of Agents").

---

## The agents

Four agents, all registered on Agentverse and chattable via ASI:One.

| Agent | Address | Role |
|---|---|---|
| `hobbyist-coordinator` | `agent1q0z45xyfa23mtk5esjas99yd20qwd2vnun9d4qk55z5s9hcasss8q7g9394` | Buyer-facing brain — intent parsing, multi-turn intake, kit synthesis, payment buyer |
| `hobbyist-scout` | `agent1qd72x35jl372z89lqlteuegm2wqfuh6cgc0muzqcduqv5wvmj8nkxxwfp9p` | Tiered listing search against the listings DB |
| `hobbyist-pricer` | `agent1qgu0efrnvgrhn4cul2le0xd9xwk54w5k755jsjg9er8mcnpfkjkcvg9km2g` | Median-comp deal scoring (`GREAT DEAL / FAIR / ABOVE MARKET`) |
| `hobbyist-payment-sink` | `agent1qwxn48r8xq7gfddwxgfejs3f2y8sfad5nyc8fkkj9yaccqvyhtvycd4tx05` | Demo seller for the Payment Protocol cycle |

Each agent has a profile README on Agentverse describing what it does and how to call it directly.

---

## What it does

1. **You** type a hobby intent in ASI:One (chatting with `hobbyist-coordinator`).
2. **Coordinator** (Claude Sonnet 4.5) parses your intent, asks clarifying follow-ups (boot size, budget, riding style, etc.), and synthesizes a structured shopping list.
3. **Coordinator → Scout** (5+ parallel JSON-op ChatMessages, one per kit item) — Scout returns real Marketplace listings from MongoDB.
4. **Coordinator → Pricer** (single batched call) — Pricer queries the listings collection for medians per `(hobby, item_type)` and returns each listing tagged with a deal verdict.
5. **Coordinator** formats the kit + listings + deal labels and replies to you.
6. *(optional)* You type `go live` → Coordinator triggers the **Payment Protocol cycle** with the PaymentSink (`init_payment` → `RequestPayment` → `CommitPayment` → `CompletePayment`) → fresh listings unlock.

End-to-end multi-agent dispatch in well under 30 seconds.

---

## Architecture

```
                    ASI:One UI / Agentverse Inspector
                                  │
                       ChatMessage / Acknowledgement
                                  │
            ┌─────────────────────▼─────────────────────┐
            │  hobbyist-coordinator                     │
            │   protocols: AgentChatProtocol,           │
            │              AgentPaymentProtocol(buyer)  │
            │   tools: query_flow.create/complete       │
            │          intent parsing, gen_followup,    │
            │          gen_list (Claude Sonnet 4.5)     │
            └────┬────────────┬─────────────────┬───────┘
                 │            │                 │
       ChatMessage{op:"search"}      ChatMessage{op:"score"}
       (one per kit item)             (single batched)
                 ▼            ▼                 ▼
   ┌───────────────────┐ ┌──────────────┐ ┌──────────────────────────┐
   │ hobbyist-scout    │ │hobbyist-     │ │hobbyist-payment-sink     │
   │  tiered Mongo     │ │pricer        │ │ AgentPaymentProtocol     │
   │  search; fallback │ │ median-comp  │ │ (seller, auto-commit)    │
   │  by hobby + head  │ │ scoring 0-100│ │ init_payment trigger →   │
   │  noun match       │ │              │ │ RequestPayment cycle     │
   └─────────┬─────────┘ └──────┬───────┘ └──────────────────────────┘
             │                  │
             └────── MongoDB Atlas ──────
              (queries, shopping_lists,
               listings — 13 seeded)
```

All four agents run in a single `uagents.Bureau` process for in-memory inter-agent dispatch (no Almanac round-trips needed for sibling messages). Each retains its own mailbox identity for inbound chats from ASI:One.

---

## Tech

- **uagents 0.24.2** + **uagents-core 0.4.4** — Chat Protocol + Payment Protocol
- **Claude Sonnet 4.5** via `anthropic` SDK — intent parsing, follow-up generation, shopping-list synthesis
- **MongoDB Atlas** via **motor** (async) — persistence
- **Pydantic v2** — typed cross-module data structures
- **Python 3.11+**, type hints throughout

---

## Run it

```bash
# 1. Install
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

# 2. Configure
cp .env.example .env
#    fill in: ANTHROPIC_API_KEY, MONGODB_URI, AGENTVERSE_API_KEY,
#             COORDINATOR_SEED, SCOUT_SEED, PRICER_SEED, PAYMENT_SINK_SEED

# 3. Seed Mongo with sample listings
.venv/bin/python seed_db.py

# 4. Print agent addresses (once, after setting seeds)
.venv/bin/python scripts/print_addresses.py

# 5. Run all four agents in a Bureau
bash scripts/run_agents.sh
#    logs: tmp/agent-logs/bureau.log

# 6. Open ASI:One, search for the coordinator address, chat with it.
#    Or use the Agentverse Inspector at the URL printed in the boot log.
```

Stop with `bash scripts/run_agents.sh stop`.

---

## Demo script (75s)

```
0–5s   slide:    "Hobbyist — turns 'I want a hobby' into a curated kit of real used listings"
5–25s  ASI:One:  "I want to get into snowboarding, $300, in LA"
                 → Coordinator asks: boot size, riding style, etc.
                 → "size 9, beginner, all-mountain"
25–45s ASI:One:  Kit reply with 6 items. Each item shows 1-2 real listings:
                   "Burton Moto size 9  $45  → GREAT DEAL (28% below median)"
                 (terminal: [scout fanout] → [scout reply] × 5 → [pricer reply])
45–65s ASI:One:  "go live"
                 → terminal: RequestPayment → CommitPayment → CompletePayment
                 → "Payment confirmed (testnet tx ABC123). Fresh results below."
65–75s slide:    Agentverse dashboard showing 4 agents online with manifest digests.
```

---

## About me / About this project

UCLA CS student, building toward Google MLOps. This project came out of frustration looking for hobby gear on OfferUp — sifting through hundreds of listings to figure out which ones are good deals at the right size, condition, and price for someone just starting out is genuinely tedious. A multi-agent network makes the search structured and explainable: one agent reasons about *what* you need, another finds candidates, another tells you whether the price is fair.

Submitted to LA Hacks 2026 for the Fetch.ai Agentverse track. The four agents above are the network. The core question we wanted to answer: *can a multi-agent setup feel like a knowledgeable friend, not a search engine?*

---

## Repo layout

```
backend/
  agents/                         # all four agents live here
    common/                       # shared messaging + addresses + session
    coordinator/                  # buyer-facing brain
    scout/                        # listings search
    pricer/                       # deal scoring
    payment_sink/                 # demo Payment Protocol seller
    run_all.py                    # Bureau entry point
  services/
    intent_parser.py              # text → structured intent (Claude)
    gen_followup.py               # next follow-up question (Claude)
    gen_list.py                   # intent → shopping list (Claude tool-use)
    query_flow.py                 # query/shopping_list lifecycle in Mongo
    listing_store.py              # OfferUp scraper output → Listing
  kitscout/                       # MongoDB layer (db, schemas, indexes)
  prompts/                        # LLM system prompts as text files
frontend/                         # Vite + React (sibling track work)
scripts/
  run_agents.sh                   # start/stop the Bureau
  print_addresses.py              # derive agent addresses from seeds
seed_db.py                        # populate Mongo with 13 sample listings
```
