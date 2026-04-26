"""Background listing search orchestration for shopping lists.

This module does not scrape OfferUp directly. It coordinates the GraphQL scraper
for each shopping-list item, persists listings, and exposes lightweight job
status for the frontend to poll while candidates stream into Mongo.
"""

import asyncio
import math
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from backend.kitscout.db import (
    listing_search_jobs,
    listings,
    queries,
    shopping_lists,
)
from backend.kitscout.schemas import ListingSearchJob
from backend.services.listing_store import upsert_scraped_listings
from backend.services.offerup_graphql import resolve_location
from backend.services.offerup_scraper import search_offerup

DEFAULT_RESULTS_PER_ITEM = 30
_INTER_ITEM_DELAY_S = 2.5
DEFAULT_SEARCH_LOCATION = "Los Angeles, CA"
ACTIVE_JOB_STALE_SECONDS = 180
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "for",
    "from",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}

_active_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_stale_active_job(existing: dict[str, Any]) -> bool:
    status = str(existing.get("status") or "")
    if status not in {"pending", "searching"}:
        return False
    started_at = existing.get("started_at")
    if isinstance(started_at, datetime):
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        age_seconds = (_now() - started_at).total_seconds()
        return age_seconds >= ACTIVE_JOB_STALE_SECONDS
    return True


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid Mongo ObjectId: {value}") from exc


def _item_included_in_search(item: dict[str, Any]) -> bool:
    """True if this line item should be scraped (same semantics as the picker)."""
    if "checked" in item and item["checked"] is not None:
        return bool(item["checked"])
    if "required" in item and item["required"] is not None:
        return bool(item["required"])
    return True


def _items_to_search(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [it for it in items if _item_included_in_search(it)]


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


def _location_from_intent(intent: dict[str, Any] | None) -> str | None:
    if not intent:
        return DEFAULT_SEARCH_LOCATION
    location = intent.get("location")
    if isinstance(location, str):
        cleaned = location.strip()
        return cleaned or DEFAULT_SEARCH_LOCATION
    if isinstance(location, dict):
        raw = location.get("raw")
        if raw:
            cleaned = str(raw).strip()
            if cleaned:
                return cleaned
        city = location.get("city")
        state = location.get("state")
        parts = [str(part) for part in (city, state) if part]
        if parts:
            return ", ".join(parts)
    return DEFAULT_SEARCH_LOCATION


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _haversine_miles(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:
    radius_miles = 3958.756
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_miles * c


def _distance_miles_for_doc(
    doc: dict[str, Any],
    *,
    center_lat: float | None,
    center_lng: float | None,
) -> float | None:
    distance = doc.get("distance") or {}
    if isinstance(distance, dict):
        raw_value = _as_float(distance.get("value"))
        unit = str(distance.get("unit") or "").lower()
        if raw_value is not None:
            if "km" in unit:
                return raw_value * 0.621371
            return raw_value

    if center_lat is None or center_lng is None:
        return None

    location = doc.get("location") or {}
    if not isinstance(location, dict):
        return None

    lat = _as_float(location.get("lat"))
    lng = _as_float(location.get("lng"))
    if lat is None or lng is None:
        return None
    return _haversine_miles(center_lat, center_lng, lat, lng)


def _tokenize(text: str) -> set[str]:
    tokens = _TOKEN_RE.findall((text or "").lower())
    return {tok for tok in tokens if tok and tok not in _STOP_WORDS}


def _query_context_text(query_doc: dict[str, Any] | None) -> str:
    if not query_doc:
        return ""

    parts: list[str] = []
    for message in query_doc.get("raw_messages") or []:
        parts.append(str(message))

    parsed_intent = query_doc.get("parsed_intent") or {}
    if isinstance(parsed_intent, dict):
        for key in ("raw_query", "hobby", "skill_level", "location"):
            value = parsed_intent.get(key)
            if value:
                parts.append(str(value))

    return " ".join(parts)


def _shopping_item_text(item: dict[str, Any] | None) -> str:
    if not item:
        return ""

    parts = [
        str(item.get("item_type") or ""),
        str(item.get("search_query") or ""),
        str(item.get("notes") or ""),
    ]
    attributes = item.get("attributes") or []
    if isinstance(attributes, list):
        for attr in attributes:
            if not isinstance(attr, dict):
                continue
            key = attr.get("key")
            if key:
                parts.append(str(key))
            for value in attr.get("value") or []:
                if isinstance(value, dict):
                    raw = value.get("value")
                    if raw:
                        parts.append(str(raw))
                elif value:
                    parts.append(str(value))
    return " ".join(parts)


def _listing_text(doc: dict[str, Any]) -> str:
    location = doc.get("location") or {}
    location_raw = location.get("raw") if isinstance(location, dict) else ""
    return " ".join(
        [
            str(doc.get("title") or ""),
            str(doc.get("description") or ""),
            str(doc.get("item_type") or ""),
            str(location_raw or ""),
        ]
    )


def _match_score(
    *,
    listing_tokens: set[str],
    query_tokens: set[str],
    item_tokens: set[str],
) -> float:
    if not listing_tokens:
        return 0.0
    if not query_tokens and not item_tokens:
        return 0.5

    query_hit = (
        len(query_tokens & listing_tokens) / len(query_tokens)
        if query_tokens
        else 0.5
    )
    item_hit = (
        len(item_tokens & listing_tokens) / len(item_tokens)
        if item_tokens
        else 0.5
    )
    score = 0.55 * query_hit + 0.45 * item_hit
    return max(0.0, min(1.0, score))


def _location_score(distance_miles: float | None) -> float:
    if distance_miles is None:
        return 0.45
    if distance_miles <= 5:
        return 1.0
    if distance_miles <= 15:
        return 0.85
    if distance_miles <= 30:
        return 0.7
    if distance_miles <= 60:
        return 0.5
    if distance_miles <= 120:
        return 0.3
    return 0.1


def _price_score(price_usd: float | None, budget_usd: float | None) -> float:
    if price_usd is None or price_usd <= 0:
        return 0.35
    if budget_usd is None or budget_usd <= 0:
        return 0.5

    ratio = price_usd / budget_usd
    if ratio <= 1:
        # Strong preference for at/under budget.
        return max(0.75, 1.0 - 0.25 * ratio)
    if ratio <= 1.5:
        # Soft penalty as listings go over budget.
        return max(0.05, 0.75 - ((ratio - 1.0) / 0.5) * 0.7)
    return 0.05


def _attach_simple_rank(
    doc: dict[str, Any],
    *,
    query_tokens: set[str],
    item_tokens: set[str],
    item_budget_usd: float | None,
) -> dict[str, Any]:
    distance_miles = _as_float(doc.get("_computed_distance_miles"))
    price_usd = _as_float(doc.get("price_usd"))
    listing_tokens = _tokenize(_listing_text(doc))

    match = _match_score(
        listing_tokens=listing_tokens,
        query_tokens=query_tokens,
        item_tokens=item_tokens,
    )
    location = _location_score(distance_miles)
    price = _price_score(price_usd, item_budget_usd)
    overall = 0.35 * location + 0.3 * price + 0.35 * match

    return {
        **doc,
        "_score_overall": round(overall, 4),
        "_score_location": round(location, 4),
        "_score_price": round(price, 4),
        "_score_match": round(match, 4),
    }


def _rank_sort_key(doc: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
    distance_miles = _as_float(doc.get("_computed_distance_miles"))
    price_usd = _as_float(doc.get("price_usd"))
    return (
        float(doc.get("_score_overall") or 0.0),
        float(doc.get("_score_match") or 0.0),
        float(doc.get("_score_location") or 0.0),
        float(doc.get("_score_price") or 0.0),
        -(distance_miles if distance_miles is not None else 1_000_000.0),
        -(price_usd if price_usd is not None else 1_000_000.0),
    )


async def _resolve_search_center(
    requested_location: str | None,
) -> tuple[str, float, float]:
    location_label = (requested_location or DEFAULT_SEARCH_LOCATION).strip()
    try:
        resolved = await resolve_location(location_label)
    except Exception:
        location_label = DEFAULT_SEARCH_LOCATION
        resolved = await resolve_location(location_label)
    return (location_label, float(resolved.latitude), float(resolved.longitude))


def _candidate_shape(
    doc: dict[str, Any],
    *,
    is_top_match: bool | None = None,
    computed_distance_miles: float | None = None,
) -> dict[str, Any]:
    location = doc.get("location") or {}
    seller = doc.get("seller") or {}
    rating = seller.get("rating_average") if isinstance(seller, dict) else None
    seller_name = seller.get("name") if isinstance(seller, dict) else None
    location_raw = location.get("raw") if isinstance(location, dict) else None
    description = doc.get("description") or ""
    photos = doc.get("photos") or []
    primary_photo = next(
        (
            photo.get("list_url") or photo.get("full_url") or photo.get("detail_url")
            for photo in photos
            if isinstance(photo, dict)
        ),
        None,
    )
    distance = doc.get("distance") or {}
    distance_label = None
    if isinstance(distance, dict) and distance.get("value") is not None:
        distance_label = f"{distance.get('value')} {distance.get('unit') or ''}".strip()
    if distance_label is None and computed_distance_miles is not None:
        distance_label = f"{computed_distance_miles:.1f} mi"

    return {
        "listing_id": doc.get("platform_id"),
        "title": doc.get("title") or "",
        "description": description or None,
        "price_usd": doc.get("price_usd"),
        "list_price_usd": None,
        "image_url": doc.get("image_url") or primary_photo,
        "photos": photos,
        "condition": doc.get("condition") or "good",
        "condition_code": doc.get("condition_code"),
        "location": location_raw or "",
        "distance": distance_label,
        "distance_miles": computed_distance_miles,
        "url": doc.get("url"),
        "seller": seller or None,
        "seller_name": seller_name,
        "rating": rating,
        "blurb": description[:180] if description else None,
        "category": doc.get("category"),
        "fulfillment": doc.get("fulfillment"),
        "is_firm_on_price": doc.get("is_firm_on_price"),
        "ranking": {
            "overall": doc.get("_score_overall"),
            "location": doc.get("_score_location"),
            "price": doc.get("_score_price"),
            "match": doc.get("_score_match"),
        },
        "is_top_match": bool(doc.get("is_top_match")) if is_top_match is None else is_top_match,
    }


async def start_search(
    shopping_list_id: str,
    *,
    max_results_per_item: int = DEFAULT_RESULTS_PER_ITEM,
) -> dict[str, Any]:
    """Create or return a background listing search job for a shopping list."""
    existing = await listing_search_jobs.find_one({"shopping_list_id": shopping_list_id})
    if existing and existing.get("status") in {"pending", "searching"} and not _is_stale_active_job(existing):
        return _serialize(existing)

    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    all_items = shopping_list.get("items") or []
    search_items = _items_to_search(all_items)
    now = _now()
    job = ListingSearchJob(
        shopping_list_id=shopping_list_id,
        status="pending",
        items_total=len(search_items),
        started_at=now,
    )
    payload = job.model_dump()

    await listing_search_jobs.replace_one(
        {"shopping_list_id": shopping_list_id},
        payload,
        upsert=True,
    )

    asyncio.create_task(
        _run_search_job(
            shopping_list_id,
            max_results_per_item=max_results_per_item,
        )
    )

    fresh = await listing_search_jobs.find_one({"shopping_list_id": shopping_list_id})
    return _serialize(fresh or payload)


async def _run_search_job(
    shopping_list_id: str,
    *,
    max_results_per_item: int,
) -> None:
    async with _active_lock:
        totals: dict[str, int] = defaultdict(int)
        try:
            shopping_list = await shopping_lists.find_one(
                {"_id": _object_id(shopping_list_id)}
            )
            if shopping_list is None:
                raise ValueError(f"Shopping list not found: {shopping_list_id}")

            query_id = shopping_list.get("query_id")
            query_doc = None
            if query_id:
                query_doc = await queries.find_one({"_id": _object_id(query_id)})
            requested_location = _location_from_intent(
                query_doc.get("parsed_intent") if query_doc else None
            )
            search_location, _, _ = await _resolve_search_center(requested_location)

            hobby = shopping_list.get("hobby") or "unknown"
            raw_items = shopping_list.get("items") or []
            items = _items_to_search(raw_items)

            await listing_search_jobs.update_one(
                {"shopping_list_id": shopping_list_id},
                {
                    "$set": {
                        "status": "searching",
                        "items_total": len(items),
                    }
                },
            )

            for index, item in enumerate(items):
                item_id = item.get("id")
                item_type = item.get("item_type") or f"item-{index}"
                search_query = item.get("search_query") or item_type
                max_price = int(item["budget_usd"]) if item.get("budget_usd") else None

                await listing_search_jobs.update_one(
                    {"shopping_list_id": shopping_list_id},
                    {
                        "$set": {
                            "current_item_id": item_id,
                            "current_item_type": item_type,
                        }
                    },
                )

                # Pace requests across items. Even with retry-on-429 in the
                # graphql layer, back-to-back per-item detail fetches are
                # what triggers OfferUp's edge throttle in the first place.
                if index > 0:
                    await asyncio.sleep(_INTER_ITEM_DELAY_S)

                # Per-item failure (e.g. 429 after retries exhausted) must
                # not abort the whole job — the user paid for a full kit
                # refresh, so we keep going and let the next item try.
                try:
                    scraped = await search_offerup(
                        search_query,
                        max_price=max_price,
                        max_results=max_results_per_item,
                        location=search_location,
                        include_details=True,
                    )
                    counts = await upsert_scraped_listings(
                        scraped,
                        search_query=search_query,
                        hobby=hobby,
                        item_type=item_type,
                        query_id=query_id,
                        list_id=shopping_list_id,
                        item_id=item_id,
                        source="offerup",
                    )
                    for key, value in counts.items():
                        totals[key] += value
                except Exception as exc:
                    totals["item_errors"] = totals.get("item_errors", 0) + 1
                    await listing_search_jobs.update_one(
                        {"shopping_list_id": shopping_list_id},
                        {
                            "$push": {
                                "item_errors": {
                                    "item_type": item_type,
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            }
                        },
                    )

                await listing_search_jobs.update_one(
                    {"shopping_list_id": shopping_list_id},
                    {
                        "$set": {
                            "items_done": index + 1,
                            "counts": dict(totals),
                        }
                    },
                )

            await listing_search_jobs.update_one(
                {"shopping_list_id": shopping_list_id},
                {
                    "$set": {
                        "status": "done",
                        "finished_at": _now(),
                        "current_item_id": None,
                        "current_item_type": None,
                        "counts": dict(totals),
                    }
                },
            )
        except Exception as exc:
            await listing_search_jobs.update_one(
                {"shopping_list_id": shopping_list_id},
                {
                    "$set": {
                        "status": "error",
                        "error": str(exc),
                        "finished_at": _now(),
                        "counts": dict(totals),
                    }
                },
            )


async def get_search_status(shopping_list_id: str) -> dict[str, Any] | None:
    doc = await listing_search_jobs.find_one({"shopping_list_id": shopping_list_id})
    return _serialize(doc) if doc else None


async def get_candidates(shopping_list_id: str) -> dict[str, list[dict[str, Any]]]:
    """Return stored candidates grouped by item id using simple robust ranking."""
    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    query_doc = None
    query_id = shopping_list.get("query_id")
    if query_id:
        query_doc = await queries.find_one({"_id": _object_id(query_id)})

    intent_location = _location_from_intent(
        query_doc.get("parsed_intent") if query_doc else None
    )
    _, center_lat, center_lng = await _resolve_search_center(intent_location)
    query_tokens = _tokenize(_query_context_text(query_doc))
    items_by_id = {
        str(item.get("id")): item
        for item in shopping_list.get("items") or []
        if item.get("id")
    }

    grouped_docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cursor = listings.find({"list_id": shopping_list_id})
    async for doc in cursor:
        item_id = doc.get("item_id")
        if not item_id:
            continue
        grouped_docs[item_id].append(doc)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item_id, item_docs in grouped_docs.items():
        docs_with_distance = []
        for doc in item_docs:
            computed_distance_miles = _distance_miles_for_doc(
                doc,
                center_lat=center_lat,
                center_lng=center_lng,
            )
            docs_with_distance.append(
                {**doc, "_computed_distance_miles": computed_distance_miles}
            )

        item = items_by_id.get(str(item_id))
        item_budget_usd = _as_float(item.get("budget_usd")) if item else None
        item_tokens = _tokenize(_shopping_item_text(item))
        scored_docs = [
            _attach_simple_rank(
                doc,
                query_tokens=query_tokens,
                item_tokens=item_tokens,
                item_budget_usd=item_budget_usd,
            )
            for doc in docs_with_distance
        ]
        ranked_docs = sorted(scored_docs, key=_rank_sort_key, reverse=True)
        if ranked_docs:
            ranked_docs[0]["is_top_match"] = True

        shaped: list[dict[str, Any]] = []
        for doc in ranked_docs:
            shaped.append(
                _candidate_shape(
                    doc,
                    computed_distance_miles=doc.get("_computed_distance_miles"),
                )
            )
        grouped[item_id] = shaped
    return grouped
