# 15-Hour Plan — "Hobbyist" Multi-Agent for Fetch.ai Agentverse Track

> **Status: pre-work ✅ done. Teammate's backend rewrite landed (`backend/api.py` exists, `query_flow.py` orchestrates the lifecycle, `listing_store.py` replaces old `ingest.py`). Total budget tightened from 15h → ~12-13h with ~2-3h buffer.**

## Context

**Why this work:** Submit to the Fetch.ai Agentverse track (1st: $2500, 2nd: $1500, 3rd: $1000) at LA Hacks 2026. The track requires AI agents registered on Agentverse, demo'd via ASI:One chat, with mandatory **Chat Protocol** and optional **Payment Protocol**. Track is named *"Search & Discovery of Agents"* — registering multiple discoverable agents that other agents can also call lifts the score.

**What we're building:** A 3-agent network on Agentverse called "Hobbyist" that turns natural-language hobby intent (e.g. *"I want to start snowboarding, $300, in LA"*) into a curated kit of real used Marketplace listings, with per-attribute reasoning, deal scoring, and FET payment gating live web scrapes.

**What we're NOT building:** A new product. Teammate already wrote the orchestration layer (`query_flow.create_query_session` + `query_flow.complete_query_session`) and the FastAPI surface (`backend/api.py`). We're wrapping `query_flow` as agent tools and (in Phase 6) rewiring the existing FastAPI endpoints to dispatch to the agents.

**Outcome:** Three publicly registered agents on Agentverse, multi-turn chat in ASI:One, real listings, real reasoning, working Payment Protocol cycle (Request → Commit → Complete), 75-sec demo video, submitted with confidence to the prize tier.

---

## Decisions locked (user-confirmed)

| Decision | Choice |
|---|---|
| Number of agents | **Three:** Coordinator + Scout + Pricer |
| Phase 2 (FastAPI → agent proxy) | **Sequential, after agents work end-to-end** |
| Frontend ActiveSearch screen | **Reframe as "Tracking" (honest, no fake activity)** |
| `kitscout/` duplicate cleanup | **✅ Done** |
| Wallet | TestNet FET, in-memory conversation state |

---

## Pre-work — ✅ COMPLETE

| Task | State |
|---|---|
| Delete `backend/services/query.py` | ✅ Already done by teammate |
| Delete `backend/services/ingest.py` | ✅ Already done by teammate (replaced by `listing_store.py`) |
| Delete root `kitscout/` (was empty) | ✅ Removed |
| `pyproject.toml` packages.find — drop `kitscout*` | ✅ Updated |
| `pip install -e ".[dev]"` to refresh editable install | ✅ Reinstalled |
| Tests still pass | ✅ 27/28 (1 pre-existing teammate test/schema mismatch — not blocking) |
| Agent seeds (`COORDINATOR_SEED`, `SCOUT_SEED`, `PRICER_SEED`) | ✅ Generated, in `.env` |
| `AGENTVERSE_API_KEY` placeholder in `.env` | ✅ Added — fill after agentverse.ai signup |
| `.env.example` documents new keys | ✅ Updated |

**Outstanding pre-work for the user:** sign up at [agentverse.ai](https://agentverse.ai), paste the key into `.env`'s `AGENTVERSE_API_KEY=`. **5 minutes.**

**Pre-existing test failure to flag teammate:** `tests/test_db.py::test_query_schema` constructs `Query(status="needs_followup")` but the new `Query.status` Literal only allows `'followups_ready' | 'shopping_list_created' | 'shopping_list_edited' | 'failed'`. Quick fix on their end — change the test or widen the Literal. **Not blocking.**

---

## What teammate built that we now leverage

This shrunk the agent work meaningfully. Concrete handoff points:

| Teammate's code | Where we use it |
|---|---|
| `backend/services/query_flow.py` — `create_query_session(user_text)` returns `{query_id, parsed_intent, followup_questions, status}` | Coordinator's first tool call (replaces 2 tool wrappers) |
| `backend/services/query_flow.py` — `complete_query_session(query_id, followup_text)` returns `{shopping_list_id, shopping_list, ...}` | Coordinator's second tool call (replaces gen_list wrapper) |
| `backend/services/query_flow.py` — `get_shopping_list(id)`, `update_shopping_list(...)` | Used if Coordinator needs to refresh / patch state |
| `backend/services/listing_store.py` — `upsert_scraped_listings(...)` | Scout's ingestion path after live scrape |
| `backend/api.py` — existing `POST /queries`, `POST /queries/{id}/answers`, `/health`, CORS already configured | Phase 6: modify these to dispatch to Coordinator instead of calling `query_flow` directly |
| `backend/kitscout/schemas.py` — `Query`, `ShoppingList`, `ShoppingListItem`, `ShoppingListAttribute`, `ShoppingListValue` | Typed return shapes from agent (frontend already expects these) |

**Schema-shape contract:** the React frontend (already wired by teammate) expects:
- `POST /queries` reply: `{query_id, parsed_intent, followup_questions, status}`
- `POST /queries/{id}/answers` reply: `{shopping_list_id, shopping_list}`

Phase 6 must preserve these exact shapes when the FastAPI proxy dispatches to the Coordinator. Coordinator's reply must map to these fields.

---

## Architecture

```
                            ASI:One UI / Agentverse Inspector
                                          │
                           ChatMessage / ChatAcknowledgement
                                          │
            ┌─────────────────────────────▼──────────────────────────────┐
            │ COORDINATOR (mailbox=True, public, port 8001)              │
            │   protocols: chat_protocol_spec v0.3.0                     │
            │              payment_protocol_spec v0.1.0 (role="buyer")   │
            │   tools: query_flow.create_query_session                   │
            │          query_flow.complete_query_session                 │
            │          (Scout/Pricer dispatch, format_for_chat)          │
            │   state: Mongo `queries` collection (teammate's session    │
            │          model) + per-sender future-correlation map        │
            └────────┬─────────────────────────────────────┬─────────────┘
                     │                                     │
       ChatMessage{op:"search",query,...}      ChatMessage{op:"score",listings,...}
                     ▼                                     ▼
   ┌──────────────────────────┐          ┌──────────────────────────┐
   │ SCOUT (mailbox, 8002)    │          │ PRICER (mailbox, 8003)   │
   │ public on Agentverse     │          │ public on Agentverse     │
   │ chat_protocol_spec       │          │ chat_protocol_spec       │
   │ tools:                   │          │ tools:                   │
   │  · mongo_search (cached) │          │  · score_against_comps   │
   │  · live_scrape (gated)   │          │ data: item_comps coll.   │
   │  · upsert_scraped_listings│          │                          │
   └──────────────────────────┘          └──────────────────────────┘
                │                                       ▲
                │      MongoDB: listings, item_comps,   │
                │      queries, shopping_lists          │
                └───────────────────────────────────────┘
```

**Inter-agent communication:** Plain `ChatMessage` objects with structured JSON in `TextContent.text` (e.g. `{"op": "search", "request_id": "...", "query": "..."}`). uagents 0.24 idiom. Scout/Pricer fall back to plain-English help if they receive non-JSON, so they're independently chattable in ASI:One.

**Library state (verified):** `uagents 0.24.2` + `uagents-core 0.4.4`. **Skip `uagents.experimental.chat_agent.ChatAgent`** — transitively imports `litellm` which isn't installed. Use bare `Agent(...)` + `Protocol(spec=chat_protocol_spec)`.

---

## File layout

```
backend/
  __init__.py                          # existing — calls load_dotenv()
  api.py                               # EXISTING (teammate) — modify in Phase 6 to proxy to agents
  agents/                              # NEW — all our work goes here
    __init__.py
    common/
      bootstrap.py                     # load_dotenv() FIRST (before kitscout.db imports)
      addresses.py                     # COORDINATOR_ADDR, SCOUT_ADDR, PRICER_ADDR (env-driven)
      session.py                       # per-sender future-correlation map (Mongo holds session state)
      messaging.py                     # send_text(ctx, to, text); extract_text(msg)
      tools.py                         # query_flow wrappers + flatten_for_chat
    coordinator/
      agent.py                         # Agent(name="hobbyist-coordinator", mailbox=True, port=8001)
      chat_handlers.py                 # @chat_proto.on_message(ChatMessage)
      payment_handlers.py              # @payment_proto.on_message(CommitPayment)
      orchestrator.py                  # plan_step(session, user_text) → Action — pure, unit-testable
    scout/
      agent.py                         # port 8002
      handlers.py                      # JSON-op router (search/live_scrape/help)
      tools.py                         # mongo_search(), live_scrape_and_ingest()
    pricer/
      agent.py                         # port 8003
      handlers.py
      scoring.py                       # score_listing_vs_comps()
    payment_sink/                      # OPTIONAL — only if buffer remains
      agent.py                         # port 8004 — minimal seller for full RequestPayment cycle
  services/                            # EXISTING — untouched
    intent_parser.py
    gen_followup.py
    gen_list.py
    scraper.py
    listing_store.py                   # NEW from teammate (replaces deleted ingest.py)
    query_flow.py                      # NEW from teammate — agent's orchestration target
    messenger.py
  kitscout/                            # EXISTING — canonical home, post-cleanup

scripts/
  run_agents.sh                        # NEW — start all 3 agents
  print_addresses.py                   # NEW — derive addresses from seeds for env wiring
```

---

## ~12-hour execution plan (was 15h, ~2-3h buffer recovered from teammate's work)

### Phase 1 — Coordinator skeleton + first ASI:One chat (2.5h, hours 0:00–2:30)

**Build:**
- `backend/agents/common/bootstrap.py` — minimal: `from dotenv import load_dotenv; load_dotenv()`. Every agent's `agent.py` imports this **before** anything else (because `backend.kitscout.db` calls `MongoClient()` at import; `motor` raises if `MONGODB_URI` unset).
- `backend/agents/common/{messaging,session,addresses}.py`
- `backend/agents/coordinator/agent.py` — `Agent(name="hobbyist-coordinator", seed=os.environ["COORDINATOR_SEED"], port=8001, mailbox=True)`. Register `Protocol(spec=chat_protocol_spec)`. Echo handler that replies `"echo: <text>"` + `ChatAcknowledgement`.
- `scripts/print_addresses.py` — derives addresses from seeds via `Identity.from_seed(seed, 0)`.

**Verify:** Run agent locally → registers on Agentverse via mailbox → open Agentverse Inspector → "Chat with Agent" → see echo. **This is the ASI:One requirement satisfied.**

**If mailbox auth fails:** fall back to `endpoint=["http://localhost:8001/submit"]` + ngrok tunnel; register endpoint manually in Agentverse. Provision ngrok account in advance.

### Phase 2 — Coordinator wraps `query_flow` for full intake → kit flow (1h, hours 2:30–3:30)

> ⚡ **Cut from 2h → 1h** — teammate's `query_flow` already does parse + followup + shopping_list orchestration. We wrap *that*, not 3 separate services.

**Build:**
- `backend/agents/common/tools.py`:
  ```python
  from backend.services.query_flow import (
      create_query_session, complete_query_session, get_shopping_list,
  )

  async def start_query(user_text: str) -> dict:
      """Returns {query_id, parsed_intent, followup_questions, status}."""
      return await create_query_session(user_text)

  async def finish_query(query_id: str, followup_text: str) -> dict:
      """Returns {shopping_list_id, shopping_list, ...}."""
      return await complete_query_session(query_id, followup_text)

  def flatten_kit_for_chat(shopping_list: dict) -> str:
      lines = [f"Kit for {shopping_list['hobby']} (${shopping_list.get('budget_usd','?')} budget):"]
      for it in shopping_list["items"]:
          attrs = " | ".join(
              f"{a['key']}={','.join(v['value'] for v in a['value'])}"
              for a in it.get("attributes", [])
          )
          tag = "required" if it.get("required") else "optional"
          lines.append(f"- {it['item_type']} ({tag})  search: \"{it['search_query']}\"  [{attrs}]")
      return "\n".join(lines)
  ```
- `backend/agents/coordinator/orchestrator.py` — pure `plan_step(session, user_text) → Action`. Action is tagged: `Reply(text)`, `CallScout(query)`, `CallPricer(listings)`, `RequestPay(amount)`. Unit-test the two main branches: "first turn → start_query → asks follow-up" and "answer → finish_query → returns kit".
- Coordinator state: per-sender `query_id` dict in memory (the actual conversation state lives in Mongo via teammate's `queries` collection — we just track which `query_id` corresponds to which ASI:One sender address).
- Replace echo handler with the real flow:
  - First message: call `start_query(user_text)`, store `query_id` keyed by sender, reply with the followup questions formatted for chat.
  - Subsequent message: call `finish_query(query_id, user_text)`, reply with flattened kit.

**Verify:** End-to-end intent → kit in ASI:One. Single agent. **Already submission-viable as a fallback.**

### Phase 3 — Scout agent + Mongo search (2.5h, hours 3:30–6:00)

**Build:**
- `backend/agents/scout/agent.py` — Agent(name="hobbyist-scout", port=8002, mailbox=True), chat protocol registered.
- `scout/handlers.py` — receives `ChatMessage` with JSON `{"op": "search", "query": ..., "max_price": ..., "city": ..., "request_id": ...}`. Replies JSON `{"request_id": ..., "listings": [...]}`. JSON parse failure → echoes a help string (so Scout is independently demoable on ASI:One).
- `scout/tools.py` — `mongo_search(query, max_price, hobby, shopping_list_id)` against `backend.kitscout.db.listings`. Filter on `shopping_list_id` if provided (matches teammate's listing schema).
- Coordinator: after `finish_query` returns the shopping_list, fan out one Scout call per item in the list. Use `_pending: dict[request_id, asyncio.Future]` keyed by `request_id`; resolve in the Scout-reply handler. Wrap in `asyncio.wait_for(fut, timeout=20.0)` to prevent deadlock.

**Verify:** Coordinator returns kit + 3-5 real Mongo listings per item. `seed_db.py` already has snowboarding data with `query_id`/`shopping_list_id` linking.

**If multi-agent send/await is flaky:** inline the Mongo lookup in Coordinator (skip Scout for v1). Document Scout as future work in submission readme. **Saves 1.5h, but you lose multi-agent rubric points — only do this in real emergency.**

### Phase 4 — Pricer agent + deal scoring (1.5h, hours 6:00–7:30)

**Build:**
- `backend/agents/pricer/agent.py` — Agent(name="hobbyist-pricer", port=8003, mailbox=True).
- `pricer/scoring.py`:
  ```python
  def score(listing, comp):
      if not comp:
          return {"deal_score": None, "label": "no_comp"}
      pct = (comp["median_price_usd"] - listing["price_usd"]) / comp["median_price_usd"]
      pct = max(-1.0, min(1.0, pct))
      score = round(50 + pct * 50)  # 0-100
      label = "great_deal" if score >= 70 else "fair" if score >= 40 else "above_market"
      return {"deal_score": score, "label": label, "pct_below_median": round(pct * 100, 1)}
  ```
- `pricer/handlers.py` — input `{"op": "score", "listings": [...]}`, output `{"request_id": ..., "scored": [...]}`. Looks up `item_comps` per listing's `item_type`.
- Coordinator: after Scout returns, batch to Pricer. Sort by `deal_score`, pick top 3 per item, format final message: `"Burton Custom 158 — $220 — 27% below median, GREAT DEAL"`.

**Verify:** Full flow: human asks → coordinator calls `start_query` → asks follow-up → calls `finish_query` → scout finds listings → pricer scores → human gets ranked list with deal labels.

### Phase 5 — Payment Protocol gating live scrape (2.5h, hours 7:30–10:00)

**Build:**
- Coordinator `payment_handlers.py`:
  - Register `Protocol(spec=payment_protocol_spec, role="buyer")`.
  - When user types "go live" / "scrape now": emit `RequestPayment(accepted_funds=[Funds(amount="0.5", currency="FET")], recipient=PAYMENT_SINK_ADDR_OR_SCOUT, deadline_seconds=120, reference=session_id, description="live FB Marketplace scrape")`.
  - On `CommitPayment`: set `session.payment_committed=True`, send `CompletePayment` back, emit `ChatMessage{"op": "live_scrape", request_id, query, max_price, query_id, shopping_list_id}` to Scout.
- Scout `live_scrape_and_ingest`:
  - Only honors `op="live_scrape"` if sender == `COORDINATOR_ADDR`.
  - Wraps `backend.services.scraper.search_marketplace` + `backend.services.listing_store.upsert_scraped_listings` (NOT the deleted `ingest.py`).
  - Returns enriched listings (with `image_path` from teammate's image work).
- **Optional `PaymentSink` agent** (only if buffer at hour 10): tiny seller agent that auto-`CommitPayment`s on `RequestPayment`. Otherwise Coordinator plays both buyer and seller via two protocol instances (looser optics, full protocol coverage).

**Verify:** Demo path works: cached results → user says "find new ones" → payment flow → Scout live-scrapes → results delivered. Full Request → Commit → Complete cycle visible in logs.

**If Browserbase flakes during demo:** fall back gracefully to cached Mongo search; payment cycle still completes (rubric credit comes from protocol message exchange, not scrape success). Pre-rehearse: *"Live scrape is queued — here's what's already on file."*

### Phase 6 — Modify existing FastAPI to dispatch to agents (1h, hours 10:00–11:00)

> ⚡ **Cut from 2h → 1h** — `backend/api.py` already exists with `/queries`, `/queries/{id}/answers`, `/health`, CORS configured. We're modifying, not building.

**Architecture:** FastAPI and agents in **different processes** (Agent.run() blocks asyncio loop; can't share with uvicorn). Add a tiny "client agent" inside FastAPI's lifespan to dispatch ChatMessages to Coordinator.

**Modify `backend/api.py`** — add an in-process proxy agent + correlation-by-request_id:

```python
# backend/api.py — additions sketch
from contextlib import asynccontextmanager
from uagents import Agent, Protocol
from uagents_core.contrib.protocols.chat import ChatMessage, chat_protocol_spec
import asyncio, os, json
from uuid import uuid4

_pending: dict[str, asyncio.Future] = {}
proxy = Agent(name="api-proxy", seed=os.environ["PROXY_SEED"], port=8010,
              endpoint=["http://localhost:8010/submit"])
proto = Protocol(spec=chat_protocol_spec)

@proto.on_message(ChatMessage)
async def on_reply(ctx, sender, msg):
    text = extract_text(msg)
    rid = parse_request_id(text)
    fut = _pending.pop(rid, None)
    if fut and not fut.done():
        fut.set_result(text)

proxy.include(proto)

@asynccontextmanager
async def lifespan(app):
    task = asyncio.create_task(proxy.run_async())
    yield
    task.cancel()

app = FastAPI(title="KitScout API", lifespan=lifespan)
# CORS already set up; keep it.

# Wrap existing /queries route in agent dispatch with circuit breaker:
@app.post("/queries")
async def create_query(body: CreateQueryRequest):
    rid = str(uuid4())
    fut = asyncio.get_event_loop().create_future()
    _pending[rid] = fut
    try:
        await send_text(proxy._ctx, COORDINATOR_ADDR,
                        json.dumps({"req_id": rid, "op": "start", "text": body.user_text}))
        agent_reply = await asyncio.wait_for(fut, timeout=30.0)
        return parse_agent_reply_to_query_response(agent_reply)
    except asyncio.TimeoutError:
        # CIRCUIT BREAKER: agent down → fall back to direct query_flow call.
        # Frontend cannot tell the difference.
        return await create_query_session(body.user_text)
```

**Coordinator changes:** accept inbound `{"req_id", "op", "text", "user", "query_id"}` shape; key sessions on `user_id` for FastAPI traffic; **echo `req_id` in every reply**; ensure final reply maps to the schema-shape contract above (`{query_id, parsed_intent, followup_questions, status}` for /queries; `{shopping_list_id, shopping_list}` for /queries/{id}/answers).

**Circuit breaker is essentially free** because `backend/api.py` already has direct `query_flow` access — we just add the if-else around the agent dispatch. **No separate `legacy.py` needed.**

**Frontend changes:** none — same endpoints, same response shapes. The proxy is transparent.

### Phase 7 — Polish, ActiveSearch reframe, rehearsal (2h, hours 11:00–13:00)

- Verify all 3 agents register on Agentverse with manifests visible.
- Test ASI:One discovery: search "snowboard hobby kit" — Coordinator should appear via protocol-manifest description. Tweak agent name/description for discoverability.
- **Reframe `frontend/src/screens/ActiveSearch.jsx`** as "Tracking" (saved listings + click-throughs, no fake activity feed / no "Negotiating $115" chips).
- Note teammate's recent design refresh (Bricolage Grotesque + Manrope + Caveat fonts, motion polish on screens) — leave it alone, it's good.
- Write submission README: agent addresses, demo video script, architecture diagram, FET amount, link to ASI:One conversation.
- Rehearse 75-second demo twice end-to-end. Record on second clean run.
- Tag commit `agentverse-v1`.

### Buffer (~2h, hours 13:00–15:00) — pick what helps most

If Phases 1-7 land clean, spend the buffer in this order:
1. **PaymentSink agent** for cleaner payment optics (~30-45 min)
2. **Searchable manifest tags** on Agentverse for ASI:One discoverability (~30 min)
3. **Demo video re-shoot** to nail timing (~30 min)
4. **Stretch:** add a Pricer "explain" mode that returns a paragraph reasoning per item (~1 hr)

If Phase X is behind, the buffer absorbs it before reaching the cut list below.

---

## Risk register (top 5)

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| 1 | **Mailbox registration fails** at demo time (Agentverse outage / network). | Show-stopper. | Pre-provision ngrok tunnels as fallback (`endpoint=[ngrok_url]`). Have screenshot proof of prior successful registration ready. Test registration twice — once 24h before, once morning-of. |
| 2 | **Browserbase / Stagehand scrape flakes** mid-demo (FB layout change, captcha). | Live-scrape moment dies. | Cached Mongo path is always primary; live scrape is bonus. Rehearse the "scrape queued, here's what's on file" line. Don't block demo flow on scrape success. |
| 3 | **Multi-agent send-and-await deadlock** — Coordinator awaits Scout, Scout fails silently. | Demo freezes. | Wrap every inter-agent call in `asyncio.wait_for(fut, timeout=20.0)`. On timeout, message user *"Trouble reaching Scout — falling back"* and run inline Mongo query. Pre-allocate the fallback path. |
| 4 | **Schema-shape mismatch** between agent reply and frontend expectations. | UI breaks (Phase 6 only). | Lock in the schema-shape contract above before Phase 6. Coordinator must reply with `{query_id, parsed_intent, followup_questions, status}` and `{shopping_list_id, shopping_list}` exactly. Add a `parse_agent_reply_to_query_response()` validator in api.py that raises on missing keys. |
| 5 | **State leakage between concurrent users** (per-sender map). | One user's query_id overwrites another. | Key on `sender` (agent address) for direct ASI:One; on `body.user_id` for FastAPI traffic. `@on_interval(60)` TTL sweep. Test with two concurrent ChatMessages. |

(Old risk #5 — "kitscout import crash" — resolved by completed pre-work.)

---

## What to cut if behind (priority order)

Cut in this order; each cut buys ~1-2h back. **Do not cross step 5 before hour 12** — multi-agent is the prize differentiator.

1. **Cut FastAPI proxy (Phase 6).** Track rubric is Agentverse + ASI:One + Chat + Payment. ASI:One web UI is a perfectly valid demo surface; React frontend is nice-to-have. **First cut, saves ~1h.**
2. **Cut PaymentSink agent.** Coordinator plays both buyer and seller via two protocol instances. Looser optics, full protocol coverage. Saves ~30min.
3. **Cut Pricer as separate agent.** Inline scoring inside Coordinator (`score()` is 30 lines). Demo voiceover says *"Pricer module"* instead of *"Pricer agent"*. Loses multi-agent rubric points but keeps user flow. Saves ~1.5h.
4. **Cut live scrape.** Demo only Mongo cached results. Payment Protocol still demonstrable as "tier upgrade unlock" stub. Saves ~1.5h.
5. **Last resort: collapse to single-agent.** Coordinator-only with all tools inline. Loses multi-agent angle. Still satisfies Chat + Payment + Agentverse + ASI:One — the floor for valid submission.

**Do not cut:** Chat Protocol, mailbox registration, intent parser, gen_list. Those are the spine.

---

## 75-second demo script

| Sec | Channel | Action / line | Visible artifact |
|-----|---------|---------------|------------------|
| 0–5 | Voiceover + arch slide | "Hobbyist is a Fetch.ai agent network that turns 'I want a hobby' into a curated kit of real used listings." | 3-agent diagram. |
| 5–15 | ASI:One | User: **"I want to get into snowboarding, $400, in LA."** | Coordinator console: `[start_query] hobby=snowboarding budget=400 location=LA`. **Reasoning rubric.** |
| 15–25 | ASI:One | Coordinator: *"Got it — boot size, riding style, skill level?"* User: **"size 10, all-mountain, beginner."** | Multi-turn memory. **Multi-turn rubric.** |
| 25–40 | ASI:One | Coordinator: *"Building your kit..."* posts flattened kit. *"Searching LA marketplace now."* Console: `→ ChatMessage to scout1q...` and `→ pricer1q...`. | Scout returns listings/item; Pricer scores. **Tool execution + multi-agent.** |
| 40–55 | ASI:One | User: **"go live — fresh listings."** Coordinator: *"Requires 0.5 FET. Sending payment request..."* Console: `RequestPayment → ...` then `← CommitPayment tx_abc123`. | Full payment cycle visible. **Payment Protocol rubric.** |
| 55–70 | ASI:One | After 10s: *"Found 3 new boards posted today. Best deal: 2023 Burton Custom 158, $220 — 27% below median. [link]"* | Real Marketplace listing. **Real-world utility.** |
| 70–75 | Voiceover | "Three agents on Agentverse, mandatory Chat Protocol, optional Payment Protocol gating live scrape, real Marketplace data via Browserbase." | Agentverse dashboard showing 3 agents online with manifest digests. |

Pre-stage all 4 terminals (Coordinator, Scout, Pricer, optional PaymentSink) on a separate monitor with `tee` colored logs.

---

## Verification (end-to-end test plan)

| Phase | How to verify | Pass criteria |
|---|---|---|
| Pre-work | ✅ Done — `pytest tests/` passes 27/28 | All except teammate's pre-existing test/schema mismatch |
| 1 | Start agent locally; chat in Agentverse Inspector | Agent listed as "online"; echo reply within 5s |
| 2 | Send "I want to snowboard for $300" via ASI:One | Coordinator asks 1+ follow-up question (from `gen_followup`); answer → kit reply (from `gen_list`) |
| 3 | Start Scout; check Coordinator logs | After kit, see `→ scout1q...` then incoming reply with listings |
| 4 | Start Pricer; ask for snowboarding kit | Final reply has deal scores like "GREAT DEAL", "FAIR" |
| 5 | Type "scrape now" / "go live" | Logs show `RequestPayment → ... ← CommitPayment ... → CompletePayment`; new listings appear |
| 6 | Frontend `POST /queries` round-trip | Returns same shape as before, but routed through agent (visible in logs); circuit breaker kicks in if Coordinator stopped — UI keeps working |
| 7 | Final demo dry-run with stopwatch | 75s walkthrough with no broken moments |

---

## Critical files for implementation

**NEW (we write these):**
- `backend/agents/coordinator/agent.py` — wires Agent + chat + payment protocols, brain of the demo. **Most-load-bearing file.**
- `backend/agents/common/tools.py` — wraps `query_flow.create_query_session` / `complete_query_session`; everything else depends on it.
- `backend/agents/common/bootstrap.py` — `load_dotenv()` first, prevents kitscout.db crash at agent startup.
- `backend/agents/coordinator/orchestrator.py` — pure `plan_step(session, user_text) → Action`; unit-testable brain logic.
- `backend/agents/scout/agent.py` — gates Browserbase scraping behind Coordinator; required for multi-agent rubric.
- `backend/agents/pricer/agent.py` — separate Pricer; multi-agent narrative.

**MODIFY (Phase 6):**
- `backend/api.py` — add proxy agent in lifespan + circuit-breaker dispatch in `/queries` and `/queries/{id}/answers` routes.

**EXISTING (reuse, do not modify):**
- `backend/services/query_flow.py` — `create_query_session`, `complete_query_session`, `get_shopping_list`, `update_shopping_list`. Coordinator's main tools.
- `backend/services/listing_store.py` — `upsert_scraped_listings`. Scout's ingest path post-live-scrape.
- `backend/services/scraper.py` — `search_marketplace`. Scout's live-scrape tool.
- `backend/kitscout/db.py` + `schemas.py` — typed return shapes.
