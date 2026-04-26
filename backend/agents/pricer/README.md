# Hobbyist Pricer

I score used-gear listings against the median price for the same hobby + item type and return a `GREAT DEAL / FAIR / ABOVE MARKET` verdict per listing. I'm called by the **Hobbyist Coordinator** after a Scout fan-out.

## What I do

Given a batch of listings, I:

1. Group by `(hobby, item_type)` and compute the median `price_usd` per group from the full listings collection (so my comp set is bigger than just the listings you sent me).
2. Score each listing on a 0-100 scale: `50 + (pct_below_median × 50)`, clamped.
3. Label each listing:
   - `great_deal` (score ≥ 58)
   - `fair` (42-57)
   - `above_market` (< 42)
   - `no_comp` (no comparable listings exist yet)

## Try me directly

```json
{
  "op": "score",
  "request_id": "abc123",
  "hobby": "snowboarding",
  "listings": [
    { "platform_id": "...", "item_type": "boots", "price_usd": 45 },
    { "platform_id": "...", "item_type": "boots", "price_usd": 80 }
  ]
}
```

I'll reply with each listing enriched:

```json
{
  "op": "score_result",
  "request_id": "abc123",
  "scored": [
    {
      "platform_id": "...",
      "item_type": "boots",
      "price_usd": 45,
      "deal_score": 64,
      "label": "great_deal",
      "pct_below_median": 28.0,
      "median_price_usd": 62.5
    },
    ...
  ]
}
```

If you ping me with non-JSON text I'll respond with this help message — I'm built for inter-agent dispatch, not freeform chat.

## Protocols

- **Chat Protocol** — JSON ops in / out.

## Tech

- Pure Python median + linear scoring (no LLM calls — fast, deterministic).
- MongoDB Atlas listings collection for comp lookups.
- Built for the LA Hacks 2026 Fetch.ai Agentverse track.
