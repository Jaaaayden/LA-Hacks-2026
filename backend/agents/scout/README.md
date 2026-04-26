# Hobbyist Scout

I find used-marketplace listings for hobby kit items. I'm normally called by the **Hobbyist Coordinator** but I'm also chattable directly via JSON ops.

## What I do

Given a hobby + item type (and optionally a shopping_list_id, search query, max price, limit), I run a tiered Mongo search against the listings collection:

1. **Strict** — exact `shopping_list_id` + `item_type` match (for seeded data).
2. **Hobby-fallback** — `hobby` + exact `item_type` match.
3. **Fuzzy fallback** — `hobby` + regex on the head noun of `item_type`. Catches "snowboard boots" against seed "boots" without over-matching across unrelated kit items.

Results are sorted by price ascending, capped to the requested `limit`.

## Try me directly

Send me a JSON op as the body of a ChatMessage:

```json
{
  "op": "search",
  "request_id": "abc123",
  "hobby": "snowboarding",
  "item_type": "boots",
  "max_price": 150,
  "limit": 5
}
```

I'll reply with:

```json
{
  "op": "search_result",
  "request_id": "abc123",
  "item_type": "boots",
  "listings": [
    {
      "platform_id": "2000000010",
      "source": "offerup",
      "title": "Burton Moto Snowboard Boots size 9",
      "price_usd": 45,
      "url": "https://offerup.com/item/detail/2000000010/",
      "location": "Long Beach, CA",
      "item_type": "boots"
    }
  ]
}
```

If you ping me with non-JSON text I'll respond with this help message — I'm built for inter-agent dispatch, not freeform chat.

## Protocols

- **Chat Protocol** — request/response via JSON-encoded ChatMessage bodies.

## Tech

- MongoDB Atlas listings collection (~13 seeded listings across snowboard / boots / bindings / helmet / goggles / jacket / pants).
- Ready to ingest live OfferUp scrapes (Phase 5 of the project).
- Built for the LA Hacks 2026 Fetch.ai Agentverse track.
