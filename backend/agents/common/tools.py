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


def format_kit_with_listings(
    shopping_list: dict[str, Any],
    listings_by_item_type: dict[str, list[dict[str, Any]] | None],
) -> str:
    """Render the kit with Scout-returned listings interleaved under each item.

    `listings_by_item_type[item_type]` is a list of listing dicts, an empty
    list (no hits), or None (Scout failed / timed out — show a soft note).
    """
    hobby = shopping_list.get("hobby", "your hobby")
    budget = shopping_list.get("budget_usd")
    budget_str = f"${budget:.0f}" if isinstance(budget, (int, float)) else "no fixed"

    items = shopping_list.get("items") or []
    if not items:
        return f"Kit for {hobby} ({budget_str} budget): (no items yet)"

    lines = [f"Kit for {hobby} ({budget_str} budget):", ""]
    for item in items:
        item_type = item.get("item_type", "item")
        item_budget = item.get("budget_usd") or 0.0
        tag = "required" if item.get("required") else "optional"

        header = f"• {item_type}  [{tag}"
        if item_budget:
            header += f", ~${item_budget:.0f}"
        header += "]"
        lines.append(header)

        listings = listings_by_item_type.get(item_type)
        if listings is None:
            lines.append("    (live search unavailable — try again)")
        elif not listings:
            lines.append("    (no listings found yet)")
        else:
            # Combined score blends Scout's user-fit relevance with
            # Pricer's deal-value score. Relevance is weighted slightly
            # heavier — wrong-size gear is worse than wrong-price gear.
            ranked = sorted(
                listings,
                key=_combined_score,
                reverse=True,
            )
            for i, lst in enumerate(ranked[:3]):
                price = lst.get("price_usd")
                price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "?"
                title = lst.get("title") or "(untitled)"
                # Long bundle titles get truncated so the link stays
                # readable in chat. The full title is still visible on the
                # OfferUp page when the user clicks through.
                if len(title) > 70:
                    title = title[:67] + "…"
                location = lst.get("location") or "—"
                url = lst.get("url")
                # Clickable markdown link when a URL is present (ASI:One,
                # Inspector, and most chat clients render this); plain
                # title otherwise.
                title_str = f"[{title}]({url})" if url else title
                tag = _deal_tag(lst)
                # Top pick gets a RECOMMENDED badge IF it actually fits the
                # user (rel > 0). A 0-relevance "best deal" doesn't earn it.
                pick_tag = ""
                if i == 0 and (lst.get("relevance_score") or 0) > 0:
                    pick_tag = "  ★ RECOMMENDED"
                lines.append(
                    f"    - {title_str}  {price_str}  [{location}]{tag}{pick_tag}"
                )
                reason = lst.get("reason")
                if reason:
                    lines.append(f"        {reason}")
        lines.append("")

    return "\n".join(lines).rstrip()
