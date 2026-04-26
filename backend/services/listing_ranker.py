"""Rank stored marketplace listings against shopping-list items.

The ranker is intentionally explainable: embedding similarity is only one
signal, blended with budget fit, hard attribute matches, deal value, listing
completeness, and the LLM relevance label.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from statistics import median
from typing import Any

from backend.services.embeddings import embed_texts

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "of",
        "with",
        "to",
        "in",
        "on",
        "at",
        "by",
        "from",
        "is",
        "are",
        "be",
        "this",
        "that",
        "it",
        "item",
        "used",
        "offerup",
    }
)

_RELEVANCE_SCORE = {
    "relevant": 1.0,
    "uncertain": 0.55,
    "irrelevant": 0.0,
}


def build_shopping_item_text(item: dict[str, Any]) -> str:
    """Stable text representation of what the buyer wants for one kit slot."""
    parts = [
        str(item.get("item_type") or ""),
        str(item.get("search_query") or ""),
        "required" if item.get("required") else "optional",
    ]
    for attr in item.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = str(attr.get("key") or "").replace("_", " ")
        values = []
        for row in attr.get("value") or []:
            if isinstance(row, dict) and row.get("value"):
                values.append(str(row["value"]))
        if key and values:
            parts.append(f"{key}: {', '.join(values)}")
    if item.get("notes"):
        parts.append(str(item["notes"]))
    return " | ".join(part for part in parts if part)


def build_listing_text(listing: dict[str, Any]) -> str:
    """Stable text representation of known listing facts."""
    parts = [
        str(listing.get("title") or ""),
        str(listing.get("description") or ""),
        str(listing.get("condition") or ""),
        str(listing.get("condition_code") or ""),
    ]

    category = listing.get("category")
    if isinstance(category, dict):
        for key in ("name", "l1_name", "l2_name", "l3_name"):
            if category.get(key):
                parts.append(str(category[key]))

    for attr in listing.get("extracted_attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = str(attr.get("key") or "").replace("_", " ")
        value = str(attr.get("value") or "")
        if key and value:
            parts.append(f"{key}: {value}")

    if listing.get("attribute_notes"):
        parts.append(str(listing["attribute_notes"]))
    return " | ".join(part for part in parts if part)


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) >= 2 and token not in _STOP_WORDS
    ]


def _sparse_embedding(text: str) -> Counter[str]:
    return Counter(_tokens(text))


def _cosine_similarity(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    common = set(left) & set(right)
    dot = sum(left[token] * right[token] for token in common)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _vector_cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _desired_attributes(item: dict[str, Any]) -> dict[str, list[str]]:
    desired: dict[str, list[str]] = {}
    for attr in item.get("attributes") or []:
        if not isinstance(attr, dict):
            continue
        key = str(attr.get("key") or "").strip()
        if not key:
            continue
        values = []
        for row in attr.get("value") or []:
            if isinstance(row, dict) and row.get("value"):
                values.append(str(row["value"]).strip())
        if values:
            desired[key] = values
    return desired


def _match_token(token: str, haystack: str) -> bool:
    if len(token) >= 3:
        return token in haystack
    return re.search(rf"\b{re.escape(token)}\b", haystack) is not None


def _attribute_fit_score(
    item: dict[str, Any],
    listing: dict[str, Any],
) -> tuple[float, list[str]]:
    desired = _desired_attributes(item)
    if not desired:
        return 0.5, []

    haystack = build_listing_text(listing).lower()
    matched: list[str] = []
    possible = 0.0
    score = 0.0
    for key, values in desired.items():
        weight = 2.0 if "size" in key.lower() else 1.0
        possible += weight
        for value in values:
            text = value.lower()
            if text in {"unknown", "unsure", "not sure", "none", "any", "n/a"}:
                continue
            tokens = re.findall(r"[a-z0-9]+", text)
            if tokens and all(_match_token(token, haystack) for token in tokens):
                score += weight
                matched.append(key)
                break

    if possible == 0:
        return 0.5, []
    return min(1.0, score / possible), matched


def _budget_fit_score(price: Any, budget: Any) -> float:
    if not isinstance(price, (int, float)) or price <= 0:
        return 0.0
    if not isinstance(budget, (int, float)) or budget <= 0:
        return 0.55

    price_float = float(price)
    budget_float = float(budget)
    if price_float <= budget_float:
        # Slightly prefer using more of the item budget over suspiciously cheap
        # listings, while still rewarding under-budget candidates.
        ratio = price_float / budget_float
        return max(0.65, min(1.0, 0.75 + ratio * 0.25))

    over_ratio = (price_float - budget_float) / budget_float
    return max(0.0, 0.65 - over_ratio)


def _deal_score(price: Any, median_price: float | None) -> tuple[float, str, float | None]:
    if not isinstance(price, (int, float)) or not median_price or median_price <= 0:
        return 0.5, "no_comp", None
    pct_below = (median_price - float(price)) / median_price
    pct_below = max(-1.0, min(1.0, pct_below))
    score = max(0.0, min(1.0, 0.5 + pct_below * 0.5))
    if score >= 0.58:
        label = "great_deal"
    elif score >= 0.42:
        label = "fair"
    else:
        label = "above_market"
    return score, label, round(pct_below * 100, 1)


def _completeness_score(listing: dict[str, Any]) -> float:
    missing_count = len(listing.get("missing_fields") or [])
    return max(0.0, 1.0 - min(missing_count, 5) * 0.16)


def _score_candidate(
    item: dict[str, Any],
    listing: dict[str, Any],
    *,
    median_price: float | None,
    semantic_similarity: float,
) -> dict[str, Any]:
    attr_score, matched_attrs = _attribute_fit_score(item, listing)
    budget = _budget_fit_score(listing.get("price_usd"), item.get("budget_usd"))
    deal, deal_label, pct_below_median = _deal_score(listing.get("price_usd"), median_price)
    completeness = _completeness_score(listing)
    relevance = _RELEVANCE_SCORE.get(str(listing.get("relevance") or "uncertain"), 0.55)

    rank_score = (
        semantic_similarity * 30
        + attr_score * 25
        + budget * 20
        + deal * 10
        + completeness * 10
        + relevance * 5
    )

    if listing.get("relevance") == "irrelevant":
        rank_score = min(rank_score, 35.0)

    return {
        "rank_score": round(rank_score, 1),
        "recommendation_label": _recommendation_label(rank_score, deal_label),
        "matched_attributes": matched_attrs,
        "score_breakdown": {
            "semantic_similarity": round(semantic_similarity, 3),
            "attribute_fit": round(attr_score, 3),
            "budget_fit": round(budget, 3),
            "deal_value": round(deal, 3),
            "completeness": round(completeness, 3),
            "relevance": round(relevance, 3),
        },
        "deal_label": deal_label,
        "pct_below_median": pct_below_median,
        "median_price_usd": round(median_price, 2) if median_price else None,
    }


def _recommendation_label(rank_score: float, deal_label: str) -> str:
    if rank_score >= 75:
        return "top_match"
    if rank_score >= 60:
        return "good_match"
    if deal_label == "great_deal" and rank_score >= 50:
        return "good_deal"
    if rank_score < 35:
        return "weak_match"
    return "possible_match"


async def _semantic_similarities(
    item_text: str,
    listing_texts: list[str],
) -> list[float]:
    embeddings = await embed_texts([item_text, *listing_texts])
    if embeddings:
        item_embedding = embeddings[0]
        return [
            _vector_cosine_similarity(item_embedding, listing_embedding)
            for listing_embedding in embeddings[1:]
        ]

    item_sparse = _sparse_embedding(item_text)
    return [
        _cosine_similarity(item_sparse, _sparse_embedding(listing_text))
        for listing_text in listing_texts
    ]


async def rank_candidates_for_item(
    item: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return candidates sorted best-first with explainable ranking metadata."""
    prices = [
        float(candidate["price_usd"])
        for candidate in candidates
        if isinstance(candidate.get("price_usd"), (int, float))
        and float(candidate["price_usd"]) >= 5
    ]
    median_price = float(median(prices)) if prices else None
    item_text = build_shopping_item_text(item)
    listing_texts = [build_listing_text(candidate) for candidate in candidates]
    semantic_scores = await _semantic_similarities(item_text, listing_texts)

    ranked = []
    for candidate, semantic_score in zip(candidates, semantic_scores):
        scored = dict(candidate)
        scored.update(
            _score_candidate(
                item,
                candidate,
                median_price=median_price,
                semantic_similarity=semantic_score,
            )
        )
        scored["is_top_match"] = False
        ranked.append(scored)

    ranked.sort(
        key=lambda row: (
            -float(row.get("rank_score") or 0),
            float(row.get("price_usd") or 1_000_000),
        )
    )
    if ranked:
        ranked[0]["is_top_match"] = True
    return ranked
