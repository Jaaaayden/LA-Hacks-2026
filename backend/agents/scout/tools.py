"""Scout's data-access layer — Mongo lookups against the listings collection."""

import re
from typing import Any

from backend.kitscout.db import listings


# Stop words we strip when tokenizing item_type for fuzzy match. Anything
# left tends to be a content noun ("boots", "helmet", "bindings").
_TOKEN_STOPWORDS = frozenset({"a", "an", "the", "for", "and", "or", "of", "with"})


def _meaningful_tokens(text: str) -> list[str]:
    """Lowercased word tokens of length >= 3, sans stopwords."""
    return [
        t
        for t in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(t) >= 3 and t not in _TOKEN_STOPWORDS
    ]


async def _find_raw(query: dict[str, Any], cap: int = 50) -> list[dict[str, Any]]:
    """Fetch a generous candidate pool for in-Python ranking. Capped to keep
    the per-request payload bounded."""
    cursor = listings.find(query).limit(cap)
    return await cursor.to_list(length=cap)


def _attribute_score(
    doc: dict[str, Any], attributes: dict[str, str] | None
) -> tuple[float, list[str]]:
    """Return (relevance_score, matched_attribute_keys) for a listing.

    Heuristic: title-substring match on each attribute value. A match worth
    1.0 per attribute. The size attribute counts double because boot/board
    sizing is the most common reason a listing would be unusable.
    Empty / 'unknown' / 'unsure' attribute values are skipped — answering
    a follow-up question with "I dunno" shouldn't filter listings out.
    """
    if not attributes:
        return 0.0, []
    title = (doc.get("title") or "").lower()
    description = (doc.get("description") or "").lower()
    haystack = f"{title} {description}"

    score = 0.0
    matched: list[str] = []
    for key, raw_value in attributes.items():
        value = (raw_value or "").strip().lower()
        if not value or value in {"unknown", "unsure", "not sure", "none", "any", "n/a"}:
            continue
        # Token-level substring: the attribute value can be multi-word
        # (e.g. "all-mountain"), splitting normalizes hyphenation. We do
        # NOT length-filter tokens here — sizes like "9" or "M" are valid
        # 1-char attribute values and the most useful signal for fit.
        tokens = re.findall(r"[a-z0-9]+", value)
        if not tokens:
            continue
        # For short tokens (1-2 chars) require a word-boundary match to
        # avoid spurious hits ("9" inside a model number). Longer tokens
        # use plain substring.
        is_size_attr = "size" in key.lower()
        if all(_match_token(t, haystack) for t in tokens):
            weight = 2.0 if is_size_attr else 1.0
            score += weight
            matched.append(key)
    return score, matched


def _match_token(token: str, haystack: str) -> bool:
    if len(token) >= 3:
        return token in haystack
    # Word-boundary regex for short tokens — "9" matches "size 9" but not
    # "152cm" or "10". Hyphens count as word boundaries.
    return re.search(rf"\b{re.escape(token)}\b", haystack) is not None


def _rank(
    docs: list[dict[str, Any]],
    attributes: dict[str, str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    """Sort by attribute-relevance descending, then price ascending."""
    scored: list[tuple[float, list[str], dict[str, Any]]] = []
    for doc in docs:
        rel, matched = _attribute_score(doc, attributes)
        scored.append((rel, matched, doc))
    # Negative score for desc sort; price asc as the secondary key.
    scored.sort(key=lambda x: (-x[0], x[2].get("price_usd") or 1e9))
    out = []
    for rel, matched, doc in scored[:limit]:
        s = _serialize_listing(doc)
        s["relevance_score"] = round(rel, 2)
        s["matched_attributes"] = matched
        out.append(s)
    return out


async def mongo_search(
    *,
    hobby: str | None = None,
    item_type: str | None = None,
    list_id: str | None = None,
    item_id: str | None = None,
    max_price: float | None = None,
    attributes: dict[str, str] | None = None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Find candidate listings for a shopping-list item.

    Three-tier candidate selection, returning the first non-empty tier:
      1. Exact `list_id` + `item_id` if both are known (most precise —
         scraped listings linked directly to a shopping-list item), else
         `list_id` + `item_type` as a softer fallback.
      2. `hobby` + exact `item_type`.
      3. `hobby` + fuzzy `item_type` regex on the head noun.

    On top of the candidate pool, results are **ranked by attribute fit**:
    listings whose title/description mentions the user's parsed attributes
    (size, riding_style, skill_level, etc.) outrank listings that don't,
    with price as the tiebreaker. This is the difference between "5 random
    boots" and "5 size-9 all-mountain beginner boots."
    """
    price_clause: dict[str, Any] = {}
    if max_price is not None and max_price > 0:
        price_clause = {"price_usd": {"$lte": float(max_price)}}

    # Tier 1: list_id + item_id (most precise). Falls back to list_id +
    # item_type if no item_id is known yet (older payloads, manual ops).
    if list_id and item_id:
        q = {**price_clause, "list_id": list_id, "item_id": item_id}
        docs = await _find_raw(q)
        if docs:
            return _rank(docs, attributes, limit)
    if list_id and item_type:
        q = {**price_clause, "list_id": list_id, "item_type": item_type}
        docs = await _find_raw(q)
        if docs:
            return _rank(docs, attributes, limit)

    # Tier 2: hobby + exact item_type, strict.
    if hobby and item_type:
        q = {**price_clause, "hobby": hobby, "item_type": item_type}
        docs = await _find_raw(q)
        if docs:
            return _rank(docs, attributes, limit)

    # Tier 3: hobby + fuzzy match on the head noun only.
    if hobby and item_type:
        tokens = _meaningful_tokens(item_type)
        if tokens:
            head = tokens[-1]
            q = {
                "hobby": hobby,
                "item_type": {"$regex": re.escape(head), "$options": "i"},
            }
            docs = await _find_raw(q)
            return _rank(docs, attributes, limit)

    return []


def _serialize_listing(doc: dict[str, Any]) -> dict[str, Any]:
    """Trim the Mongo doc to fields the chat reply needs (and JSON-safe)."""
    loc = doc.get("location") or {}
    city = loc.get("city")
    state = loc.get("state")
    location_str = ", ".join(p for p in (city, state) if p) or loc.get("raw")
    return {
        "platform_id": doc.get("platform_id"),
        "source": doc.get("source"),
        "title": doc.get("title"),
        "price_usd": doc.get("price_usd"),
        "url": doc.get("url"),
        "location": location_str,
        "item_type": doc.get("item_type"),
    }
