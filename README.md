# hobbify — a multi-agent buyer-side AI for hobbyists

> *"I want to get into snowboarding, $300, in LA"* → a curated kit of real used-marketplace listings, scored against the median price, with on-demand fresh-scrape unlocks gated by the Fetch.ai Payment Protocol.

LA Hacks 2026 — Fetch.ai Agentverse track ("Search & Discovery of Agents").

---

## Fetch.ai submission

Built for the **Fetch.ai Agentverse track — Search & Discovery of Agents** at LA Hacks 2026.

### Why hobbify fits the track

- **Multi-agent network, not a single-LLM wrapper.** Every user message fans out across four independently registered agents: `hobbyist-coordinator` (intake + synthesis), `hobbyist-scout` (search), `hobbyist-pricer` (deal scoring), and `hobbyist-payment-sink` (Payment Protocol seller). Each one is discoverable on Agentverse and individually chattable from ASI:One.
- **All inter-agent dispatch uses uAgents `AgentChatProtocol`.** Coordinator → Scout fans out one structured `ChatMessage{op:"search"}` per kit item in parallel; Coordinator → Pricer is a single batched `ChatMessage{op:"score"}`. Every hop shows up in the Agentverse Inspector.
- **Payment Protocol on testnet, end-to-end.** Saying `go live` triggers `init_payment → RequestPayment → CommitPayment → CompletePayment` between `hobbyist-coordinator` (buyer) and `hobbyist-payment-sink` (seller, auto-commit). The testnet tx ID is surfaced back to the user in the chat reply.
- **ASI:One is the only UI required for the core flow.** Users find `hobbyist-coordinator` on ASI:One and chat with it like a knowledgeable friend — no custom frontend needed to demo the agent network.

### How the agents reason and talk to each other

Each user message kicks off the following multi-agent dispatch — every hop is a uAgents `ChatMessage` and shows up in the Agentverse Inspector:

1. **User → `hobbyist-coordinator`** (via ASI:One) — natural-language hobby intent (e.g. *"I want to get into soccer but I don't know what to get"*).
2. **Coordinator reasons about intent** — Claude Sonnet 4.5 parses the message into a structured intent, decides which clarifying questions are still missing (budget, sizes, surface, fit, etc.), and replies with a *single bundled* follow-up message instead of round-tripping each question.
3. **Coordinator synthesizes a kit** — once the user answers, Coordinator generates a structured shopping list (item names, required-vs-optional, per-item budget allocations) using Claude tool-use against the parsed intent.
4. **Coordinator → `hobbyist-scout`** — fans out **N parallel** `ChatMessage{op:"search", item}` (one per kit item). Scout queries MongoDB with tiered fallback (exact item match → hobby + head-noun match) and returns matching listings per item.
5. **Coordinator → `hobbyist-pricer`** — **single batched** `ChatMessage{op:"score", listings}`. Pricer pulls per-`(hobby, item_type)` price medians from Mongo and tags each listing 🟢 GREAT DEAL / 🟡 FAIR / 🔴 ABOVE MARKET with a one-line rationale.
6. **Coordinator → User** — formats kit + scored listings into a single ASI:One reply.
7. *(optional)* **User says `go live` → Coordinator → `hobbyist-payment-sink`** — full Payment Protocol cycle: `init_payment` → `RequestPayment` → `CommitPayment` → `CompletePayment`. The testnet tx ID is surfaced back into the user reply, and a fresh-listings scrape unlocks for the kit.

All four agents run inside one `uagents.Bureau` so sibling-to-sibling messages stay in-process (no Almanac round-trips), but every agent keeps its own mailbox identity so it remains independently chattable from ASI:One.

### Deliverables

- **ASI:One chat session:** https://asi1.ai/chat/a2d03b4c-0b91-4a1c-800a-72f68000faa3
- **Agentverse agent profiles:**
  - `hobbyist-coordinator` — https://agentverse.ai/agents/details/agent1q0z45xyfa23mtk5esjas99yd20qwd2vnun9d4qk55z5s9hcasss8q7g9394/profile
  - `hobbyist-scout` — https://agentverse.ai/agents/details/agent1qd72x35jl372z89lqlteuegm2wqfuh6cgc0muzqcduqv5wvmj8nkxxwfp9p/profile
  - `hobbyist-pricer` — https://agentverse.ai/agents/details/agent1qgu0efrnvgrhn4cul2le0xd9xwk54w5k755jsjg9er8mcnpfkjkcvg9km2g/profile
  - `hobbyist-payment-sink` — https://agentverse.ai/agents/details/agent1qwxn48r8xq7gfddwxgfejs3f2y8sfad5nyc8fkkj9yaccqvyhtvycd4tx05/profile
- **Latest Payment Protocol testnet tx:** `TESTNET-825A098DAD484303` (from a live-listings unlock cycle)

### Fetch.ai tech used

| Capability | Where it lives |
|---|---|
| `uagents` Bureau (in-process multi-agent dispatch) | `backend/agents/run_all.py` |
| `AgentChatProtocol` for ASI:One + inter-agent messaging | every agent under `backend/agents/` |
| `AgentPaymentProtocol` (buyer + seller roles) | `backend/agents/coordinator/` (buyer), `backend/agents/payment_sink/` (seller) |
| Agentverse mailbox identities (one per agent) | derived from `*_SEED` env vars via `scripts/print_addresses.py` |
| ASI:One natural-language discoverability | `hobbyist-coordinator` registered with a buyer-facing chat manifest |

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

### How the Payment Protocol creates value

The first time you ask about a hobby that hasn't been searched before, **the initial kit comes back with empty slots** — there is nothing in our listings database yet, so Scout has nothing to surface. The kit shows the items you need (with the right shape, sizing, and budget allocation that Coordinator + Claude reasoned about), but each slot is blank with a prompt that says *"Hunting for fresh listings — say `go live` to scrape OfferUp for this item right now."*

When you say **`go live`**, the agents run the full **Payment Protocol** cycle on testnet (0.5 FET): Coordinator (buyer) ↔ PaymentSink (seller) exchange `init_payment → RequestPayment → CommitPayment → CompletePayment`. The successful settlement is what **gates the live OfferUp scrape** — the moment `CompletePayment` lands, Coordinator triggers a fresh scrape across every kit item, persists the listings into Mongo, re-runs Scout + Pricer, and replies with a populated kit prefixed with the testnet transaction id.

That is the demo arc visible in the linked ASI:One chat:

1. **Empty kit** with `say go live` prompts under each item — no data on file yet
2. **`go live`** → Payment Protocol cycle completes (visible in chat as `Payment confirmed (testnet tx TESTNET-…)`)
3. **Fresh kit** with real OfferUp listings + Pricer deal scores, posted as `Fresh results (tx TESTNET-…)`

Cached results from prior queries are free; fresh data is gated behind the protocol cycle. That is the concrete value the optional Payment Protocol unlocks.

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
