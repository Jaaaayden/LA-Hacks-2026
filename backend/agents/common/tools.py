"""Coordinator-side tool wrappers around teammate's `query_flow`.

These are thin passthroughs plus chat-friendly formatters. The agent's state
machine lives in the coordinator's chat handler — these are just the I/O.
"""

from typing import Any

from backend.services.query_flow import (
    complete_query_session,
    create_query_session,
    get_shopping_list,
)

__all__ = [
    "start_query",
    "finish_query",
    "fetch_shopping_list",
    "format_followup_questions",
    "flatten_kit_for_chat",
    "format_kit_with_listings",
]


async def start_query(user_text: str) -> dict[str, Any]:
    """First turn — parse intent + generate initial follow-ups.

    Returns: {query_id, parsed_intent, followup_questions, status,
              questions_asked_count, max_followup_questions, done}
    """
    return await create_query_session(user_text)


async def finish_query(query_id: str, followup_text: str) -> dict[str, Any]:
    """Subsequent turn — answer follow-ups, possibly building the kit.

    Returns either:
      - more follow-ups: {..., status: "followups_ready", done: False}
      - the kit:         {..., shopping_list_id, shopping_list, done: True}
    """
    return await complete_query_session(query_id, followup_text)


async def fetch_shopping_list(shopping_list_id: str) -> dict[str, Any] | None:
    return await get_shopping_list(shopping_list_id)


def format_followup_questions(questions: list[str]) -> str:
    if not questions:
        return (
            "I have enough to start building your kit. "
            "Reply with anything (e.g. 'go') and I'll put it together."
        )
    lines = ["A few quick questions so I can build the right kit:"]
    for i, q in enumerate(questions, 1):
        lines.append(f"  {i}. {q}")
    lines.append("\nAnswer in one message — short answers are fine.")
    return "\n".join(lines)


def flatten_kit_for_chat(shopping_list: dict[str, Any]) -> str:
    hobby = shopping_list.get("hobby", "your hobby")
    budget = shopping_list.get("budget_usd")
    budget_str = f"${budget:.0f}" if isinstance(budget, (int, float)) else "no fixed"

    items = shopping_list.get("items") or []
    if not items:
        return f"Kit for {hobby} ({budget_str} budget): (no items yet — try a more specific intent)"

    lines = [f"Kit for {hobby} ({budget_str} budget):", ""]
    for item in items:
        item_type = item.get("item_type", "item")
        search_query = item.get("search_query", "")
        item_budget = item.get("budget_usd") or 0.0
        tag = "required" if item.get("required") else "optional"

        header = f"• {item_type}  [{tag}"
        if item_budget:
            header += f", ~${item_budget:.0f}"
        header += "]"
        lines.append(header)
        if search_query:
            lines.append(f"    search: \"{search_query}\"")

        attrs = item.get("attributes") or []
        for attr in attrs:
            key = attr.get("key", "")
            values = attr.get("value") or []
            value_strs = [v.get("value", "") for v in values if v.get("value")]
            if key and value_strs:
                lines.append(f"    {key}: {', '.join(value_strs)}")

        notes = item.get("notes")
        if notes:
            lines.append(f"    note: {notes}")
        lines.append("")

    lines.append("Next: I'll search live listings against each item. (coming in the next phase)")
    return "\n".join(lines).rstrip()


def _combined_score(listing: dict[str, Any]) -> float:
    """Rank listings by a blend of user-fit and deal value.

    `relevance_score` is unbounded (typically 0-4 — sum of attribute
    weights). `deal_score` is 0-100. Normalize the deal piece to roughly
    the same range, then weight relevance ~1.5× because wrong-size gear
    is unusable while wrong-priced gear is just suboptimal.
    """
    rel = float(listing.get("relevance_score") or 0)
    deal = float(listing.get("deal_score") or 50) / 50.0  # ~0-2
    return rel * 1.5 + deal


_LABEL_TO_BADGE = {
    "great_deal": "GREAT DEAL",
    "fair": "FAIR",
    "above_market": "ABOVE MARKET",
    "no_comp": "",
}


def _deal_tag(listing: dict[str, Any]) -> str:
    label = listing.get("label")
    pct = listing.get("pct_below_median")
    badge = _LABEL_TO_BADGE.get(label or "", "")
    if not badge:
        return ""
    if isinstance(pct, (int, float)) and pct > 0:
        return f"  → {badge} ({pct:.0f}% below median)"
    if isinstance(pct, (int, float)) and pct < 0:
        return f"  → {badge} ({abs(pct):.0f}% above median)"
    return f"  → {badge}"


# Reason prefixes that indicate the LLM doesn't actually recommend the
# listing. Hide these from the chat output — keeping them around just adds
# noise. The LLM still sees them when scoring; we just don't surface them.
_DUD_PREFIXES = (
    "skip:", "skip ", "pass:", "pass ",
    "avoid:", "avoid ", "wrong item", "wrong size", "don't",
    "high risk:", "do not", "stay away",
)


def _is_dud(listing: dict[str, Any]) -> bool:
    reason = (listing.get("reason") or "").strip().lower()
    return any(reason.startswith(p) for p in _DUD_PREFIXES)


def _dedupe(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop duplicates. Two passes:
      1. Exact platform_id / url match (same listing scraped twice).
      2. Same title + price + location (sellers commonly relist the same
         physical item under fresh OfferUp item IDs — looks like duplicates
         to the user even though Mongo sees them as distinct rows).
    Keeps the first occurrence; combined with score-based ranking that's
    the best-scored representative copy."""
    seen_ids: set[str] = set()
    seen_signatures: set[tuple[str, float, str]] = set()
    out: list[dict[str, Any]] = []
    for lst in listings:
        key = str(lst.get("platform_id") or lst.get("url") or "")
        if key and key in seen_ids:
            continue
        title = (lst.get("title") or "").strip().lower()
        price = float(lst.get("price_usd") or 0)
        location = (lst.get("location") or "").strip().lower()
        signature = (title, price, location)
        if title and signature in seen_signatures:
            continue
        if key:
            seen_ids.add(key)
        if title:
            seen_signatures.add(signature)
        out.append(lst)
    return out


def _format_listing_block(
    lst: dict[str, Any], is_top_pick: bool
) -> list[str]:
    """One markdown block per listing — clickable title, price+location
    line, optional deal verdict, italic reason. Blank line above so the
    chat client renders the block as its own paragraph."""
    price = lst.get("price_usd")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "?"
    title = lst.get("title") or "(untitled)"
    if len(title) > 65:
        title = title[:62] + "…"
    location = lst.get("location") or "—"
    url = lst.get("url")
    title_md = f"**[{title}]({url})**" if url else f"**{title}**"

    badge = ""
    if is_top_pick and (lst.get("relevance_score") or 0) > 0:
        badge = "  ★ **RECOMMENDED**"

    label = lst.get("label")
    pct = lst.get("pct_below_median")
    if label == "great_deal" and isinstance(pct, (int, float)) and pct > 0:
        verdict = f" · 🟢 GREAT DEAL ({pct:.0f}% below median)"
    elif label == "above_market" and isinstance(pct, (int, float)) and pct < 0:
        verdict = f" · 🔴 ABOVE MARKET ({abs(pct):.0f}% above median)"
    elif label == "fair":
        verdict = " · 🟡 FAIR"
    else:
        verdict = ""

    block = ["", f"{title_md}{badge}", f"{price_str} · {location}{verdict}"]
    reason = lst.get("reason")
    if reason:
        block.append(f"_{reason}_")
    return block


def format_kit_with_listings(
    shopping_list: dict[str, Any],
    listings_by_item_type: dict[str, list[dict[str, Any]] | None],
) -> str:
    """Render the kit with Scout-returned listings interleaved under each
    item, formatted for chat readability:
      - Markdown headers per kit slot
      - Up to 3 deduped, non-dud listings per slot
      - Clickable title, price · location, deal verdict, italic LLM reason
      - First listing per slot gets ★ RECOMMENDED if it actually fits
    """
    hobby = shopping_list.get("hobby", "your hobby")
    budget = shopping_list.get("budget_usd")
    budget_str = f"${budget:.0f}" if isinstance(budget, (int, float)) else "no fixed"

    items = shopping_list.get("items") or []
    if not items:
        return f"**Kit for {hobby} — {budget_str} budget:** (no items yet)"

    lines: list[str] = [f"## Kit for {hobby} — {budget_str} budget"]

    for item in items:
        item_type = item.get("item_type", "item")
        item_budget = item.get("budget_usd") or 0.0
        required = "required" if item.get("required") else "optional"
        budget_marker = f"~${item_budget:.0f}" if item_budget else ""
        suffix_parts = [required] + ([budget_marker] if budget_marker else [])
        suffix = " · ".join(suffix_parts)

        lines.append("")
        lines.append("---")
        lines.append(f"### {item_type.title()}  ({suffix})")

        listings = listings_by_item_type.get(item_type)
        if listings is None:
            lines.append("")
            lines.append("_(live search unavailable — try again)_")
            continue

        # 1. Dedupe by platform_id / url.
        # 2. Drop "Skip:" / "Wrong item:" listings the LLM flagged as bad.
        # 3. Rank by combined Scout-relevance + Pricer-deal-value score.
        unique = _dedupe(listings)
        good = [l for l in unique if not _is_dud(l)]
        ranked = sorted(good or unique, key=_combined_score, reverse=True)

        if not ranked:
            lines.append("")
            lines.append(
                "_Hunting for fresh listings — say `go live` to "
                "scrape OfferUp for this item right now._"
            )
            continue

        for i, lst in enumerate(ranked[:3]):
            lines.extend(_format_listing_block(lst, is_top_pick=(i == 0)))

    return "\n".join(lines).rstrip()
