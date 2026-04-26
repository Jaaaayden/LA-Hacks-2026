"""Background listing search orchestration for shopping lists.

This module does not scrape OfferUp directly. It coordinates the GraphQL scraper
for each shopping-list item, persists listings, and exposes lightweight job
status for the frontend to poll while candidates stream into Mongo.
"""

import asyncio
import math
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
DEFAULT_SEARCH_LOCATION = "Los Angeles, CA"

_active_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid Mongo ObjectId: {value}") from exc


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


def _candidate_sort_key(
    doc: dict[str, Any],
    *,
    center_lat: float | None,
    center_lng: float | None,
) -> tuple[float, float]:
    distance_miles = _distance_miles_for_doc(
        doc,
        center_lat=center_lat,
        center_lng=center_lng,
    )
    distance_rank = distance_miles if distance_miles is not None else 1_000_000.0
    price_rank = _as_float(doc.get("price_usd")) or 1_000_000.0
    return (distance_rank, price_rank)


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
    is_top_match: bool = False,
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
        "missing_fields": doc.get("missing_fields") or [],
        "seller_questions": doc.get("seller_questions") or [],
        "is_top_match": is_top_match,
    }


async def start_search(
    shopping_list_id: str,
    *,
    max_results_per_item: int = DEFAULT_RESULTS_PER_ITEM,
) -> dict[str, Any]:
    """Create or return a background listing search job for a shopping list."""
    existing = await listing_search_jobs.find_one({"shopping_list_id": shopping_list_id})
    if existing and existing.get("status") in {"pending", "searching"}:
        return _serialize(existing)

    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    items = shopping_list.get("items") or []
    now = _now()
    job = ListingSearchJob(
        shopping_list_id=shopping_list_id,
        status="pending",
        items_total=len(items),
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
            items = shopping_list.get("items") or []

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
    """Return stored candidates grouped by item id, prioritized by location."""
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

    grouped_docs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cursor = listings.find({"list_id": shopping_list_id})
    async for doc in cursor:
        item_id = doc.get("item_id")
        if not item_id:
            continue
        grouped_docs[item_id].append(doc)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item_id, item_docs in grouped_docs.items():
        ranked_docs = sorted(
            item_docs,
            key=lambda doc: _candidate_sort_key(
                doc,
                center_lat=center_lat,
                center_lng=center_lng,
            ),
        )
        shaped: list[dict[str, Any]] = []
        for idx, doc in enumerate(ranked_docs):
            shaped.append(
                _candidate_shape(
                    doc,
                    is_top_match=(idx == 0),
                    computed_distance_miles=_distance_miles_for_doc(
                        doc,
                        center_lat=center_lat,
                        center_lng=center_lng,
                    ),
                )
            )
        grouped[item_id] = shaped
    return grouped
