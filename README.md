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

## The problem

Trying to start a new hobby on a budget means buying secondhand gear, which means dealing with marketplaces like OfferUp. That experience has four specific frictions stacked on top of each other:

1. **You don't know what to buy.** A snowboard kit isn't just a snowboard — it's bindings, boots, a helmet, sometimes goggles and gloves. A surfing kit isn't just a board. Beginners don't know the full bill of materials.
2. **Listings are unstructured.** Titles like *"snowboard 158 used good cond"* don't tell you the brand, riding style, skill level it's appropriate for, or whether the bindings are included.
3. **You don't know what's a fair price.** A $180 board could be a great deal or a rip-off depending on the model and condition. You'd have to comparison-shop across dozens of listings to develop intuition.
4. **Inventory turns over fast.** A "saved search" is stale within hours; you have to re-scrape constantly.

hobbify maps each friction to a specific agent:

- **Coordinator** answers *"what do I need"* by parsing your intent and synthesizing a structured kit (with required-vs-optional, per-item budget allocations, hobby-specific attributes like riding style or boot size).
- **Scout** answers *"what's available"* via tiered Mongo search with attribute-aware ranking (size matches and style matches outrank generic listings).
- **Pricer** answers *"is this a good deal"* via median-price comparison per `(hobby, item_type)` bucket, tagging each listing 🟢 GREAT DEAL / 🟡 FAIR / 🔴 ABOVE MARKET with a one-line rationale.
- **PaymentSink** + Coordinator's payment role answer *"can I pay for fresh data"* via the Fetch.ai Payment Protocol — completing the cycle gates a live OfferUp scrape so users don't have to wait for the next nightly batch.

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

## Notable design decisions

A few choices in the agent code that aren't obvious from the surface:

- **Single Bureau, four mailboxes.** Coordinator → Scout dispatch needs reliable address resolution. Almanac registration on testnet is flaky without a funded wallet, so we run all four agents in one `uagents.Bureau` for in-process address resolution. Each agent still keeps its own mailbox identity, so it remains independently chattable from ASI:One — judges can chat directly with Scout or Pricer to verify they work standalone.

- **Background scout/pricer dispatch is mandatory, not stylistic.** uagents serializes inbound chat handlers per agent. If Coordinator awaited Scout's reply inline inside `on_chat`, Scout's reply would queue behind the same handler that's waiting for it → deadlock. So `_kit_and_listings_reply` runs as `asyncio.create_task` after `on_chat` returns, freeing the handler to receive Scout's reply, which then triggers a separate background coroutine to send the user the final kit message.

- **Two correlation maps for the Payment Protocol.** `CompletePayment` only carries `transaction_id`, not the original `reference`. To thread the user-flow context across the multi-message cycle, Coordinator keeps `_payment_user_by_ref` (ref → user, populated when we trigger the cycle) and `_tx_to_user` (tx → user, populated when we mint the `CommitPayment`). Multiple in-flight payments don't cross-pollinate.

- **Scout's tiered fallback search.** Four tiers, most specific first: (1) `list_id + item_id` exact match for listings linked to this kit slot, (2) `list_id + item_type` softer fallback, (3) `hobby + item_type` strict, (4) `hobby + fuzzy head-noun` regex. Plus a fifth cross-hobby fallback gated by a hand-curated whitelist (`helmet`, `goggles`, `gloves`, `jacket`…) for genuinely shared gear — but never sport-specific items like boots, bindings, or boards.

- **Attribute-aware ranking.** Scout pulls a 50-doc candidate pool and re-ranks in Python by *attribute fit* against parsed user attributes (size, riding_style, skill_level, etc.). Title-substring match on each attribute earns relevance points; size matches count double because boot/board sizing is the most common reason a listing is unusable. Price is the tiebreaker.

- **Per-item failure isolation in the live scrape.** A 429 on item 5 of 8 doesn't kill the whole job — each item is wrapped in try/except, failures bump a counter on the job doc and the loop keeps going. The user paid 0.5 FET for a kit refresh; partial coverage is far better than nothing.

- **OfferUp 429 retry with `Retry-After` honoring.** `_post_graphql` and `get_offerup_listing_detail` both retry up to 3 times on HTTP 429, honoring the server's `Retry-After` header when present, falling back to 5/15/45s exponential backoff otherwise. Combined with `detail_concurrency=2` and `_INTER_ITEM_DELAY_S=2.5`, this keeps total throughput under OfferUp's edge throttle window in most demo conditions.

- **Pricer's median-comp scoring.** For each `(hobby, item_type)` bucket, Pricer pulls all comparable listing prices from Mongo, computes the median, and tags each new listing by percentage above/below. The label thresholds (>15% below = GREAT DEAL, within ±15% = FAIR, >15% above = ABOVE MARKET) are tuned for used-gear marketplaces where bargaining is normal. Pricer also generates a one-line rationale per listing tying the verdict to the user's parsed attributes.

---

## Data model

Four MongoDB Atlas collections via `motor` (async):

| Collection | What it stores | Key index |
|---|---|---|
| `queries` | Original user text + parsed structured intent + follow-up state | `_id` |
| `shopping_lists` | Generated kit (hobby, items, per-item budget allocation, attributes, search_query) | `_id`, `query_id` |
| `listings` | Scraped OfferUp listings with `list_id` + `item_id` linkage to kit slots | unique `(platform_id, source)`, plus `list_id`/`hobby`/`item_type` for Scout's tiered queries |
| `listing_search_jobs` | Background scrape state for "go live" flows (status, items_done, counts, item_errors) | `shopping_list_id` |

The `(platform_id, source)` unique index is what lets `upsert_scraped_listings` be idempotent — re-scraping the same OfferUp listing updates it instead of creating a duplicate, so the live-scrape path can run repeatedly without exploding the listings collection.

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

## Limitations & honest tradeoffs

What's intentional, what's a known rough edge, and what we'd address with more time.

- **Payment is symbolic, not on-chain.** Transaction IDs are minted as `TESTNET-<uuid>`. The Payment Protocol message exchange is wire-compatible with mainnet — funding the wallets via the Fetch.ai testnet faucet would let us actually settle FET, but the rubric scores the protocol cycle, not real-money transfer.
- **OfferUp rate-limits detail enrichment hard after sustained scraping.** The search GraphQL endpoint is reliable; the per-listing detail GET endpoint gets 429'd aggressively once the throttle warms up on your IP. Mitigations are in place (retry-on-429, lowered concurrency, `DEFAULT_RESULTS_PER_ITEM=10`, inter-item pacing), but during back-to-back live scrapes you may still see some empty kit slots — the cycle still completes, just with fewer listings than ideal.
- **Cross-hobby fallback is a hand-curated whitelist.** Scout's tier-4 fallback only borrows listings across hobbies for genuinely shared gear (helmets, gloves, jackets, beanies). Sport-specific items (boots, bindings, boards, surfboards, fins) are deliberately excluded — a snowboard boot isn't a ski boot. Adding a new hobby means adding its truly-shared items to the whitelist.
- **No image rendering in the chat surface.** ASI:One's chat protocol is text-only — listings appear as clickable URLs, not embedded photos. The teammate-built `frontend/` Vite + React app renders images, but the agent track demo lives in ASI:One.
- **Conversation state is per-process.** The Coordinator's session map (sender → query_id → shopping_list_id) lives in memory; restarting the bureau loses in-flight conversations. The Mongo persistence covers parsed intents, kits, and listings — only the lightweight session state is lost.
- **Single seller in the Payment Protocol.** PaymentSink is one demo agent that auto-commits anything Coordinator initiates. A real implementation would have per-seller funding, a public price list, and human-in-the-loop authorization for non-symbolic amounts.

### Future work

If we kept building past the hackathon:

- **Actual on-chain settlement** via funded testnet/mainnet wallets so the FET transfers are real.
- **Negotiation agent** — there's already a `backend/prompts/negotiator.txt` and `bargain.py` from earlier exploration. A separate negotiator agent could draft seller messages and orchestrate the back-and-forth.
- **Cross-marketplace adapters** — Craigslist + Facebook Marketplace + eBay scrapers feeding the same `listings` collection. The schema already abstracts platform via `(platform_id, source)`.
- **Saved searches with push notifications via Agentverse** — Scout could subscribe to background scrapes and push new matches to the user's coordinator session as they appear.
- **Image-based attribute extraction** — running detail-page photos through a vision model to extract attributes the seller didn't mention (size labels visible in the photo, condition signals, etc.).


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
