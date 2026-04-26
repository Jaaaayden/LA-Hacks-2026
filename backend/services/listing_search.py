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
from backend.services.listing_attribute_extractor import extract_listing_attributes
from backend.services.listing_ranker import rank_candidates_for_item
from backend.services.listing_store import parse_platform_id, upsert_scraped_listings
from backend.services.offerup_graphql import resolve_location
from backend.services.offerup_scraper import search_offerup

DEFAULT_RESULTS_PER_ITEM = 30
_INTER_ITEM_DELAY_S = 2.5
DEFAULT_SEARCH_LOCATION = "Los Angeles, CA"
# Temporary kill-switches for in-progress recommender work.
ENABLE_RECOMMENDATION_RANKING = False
ENABLE_LISTING_ATTRIBUTE_ANALYSIS = False

_active_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        "relevance": doc.get("relevance") or "uncertain",
        "extracted_attributes": doc.get("extracted_attributes") or [],
        "missing_fields": doc.get("missing_fields") or [],
        "attribute_notes": doc.get("attribute_notes"),
        "seller_questions": doc.get("seller_questions") or [],
        "is_top_match": bool(doc.get("is_top_match")) if is_top_match is None else is_top_match,
    }


async def _extract_and_store_listing_attributes(
    scraped: list[dict[str, Any]],
    *,
    shopping_item: dict[str, Any],
    hobby: str,
) -> dict[str, int]:
    if not scraped:
        return {"analyzed": 0, "analysis_errors": 0}

    try:
        analyses = await asyncio.to_thread(
            extract_listing_attributes,
            scraped,
            shopping_item=shopping_item,
            hobby=hobby,
        )
    except Exception:
        return {"analyzed": 0, "analysis_errors": len(scraped)}

    analyzed = 0
    for raw in scraped:
        platform_id = parse_platform_id(str(raw.get("url") or ""))
        if not platform_id:
            continue
        analysis = analyses.get(platform_id)
        if not analysis:
            continue
        await listings.update_one(
            {"platform_id": platform_id, "source": "offerup"},
            {
                "$set": {
                    "relevance": analysis["relevance"],
                    "extracted_attributes": analysis["extracted_attributes"],
                    "missing_fields": analysis["missing_fields"],
                    "seller_questions": analysis["seller_questions"],
                    "attribute_notes": analysis["attribute_notes"],
                }
            },
        )
        analyzed += 1

    return {"analyzed": analyzed, "analysis_errors": 0}


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
                    analysis_counts = await _extract_and_store_listing_attributes(
                        scraped,
                        shopping_item=item,
                        hobby=hobby,
                    )
                    for key, value in analysis_counts.items():
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
        if ENABLE_RECOMMENDATION_RANKING and item:
            ranked_docs = await rank_candidates_for_item(item, docs_with_distance)
        else:
            ranked_docs = sorted(
                docs_with_distance,
                key=lambda doc: _candidate_sort_key(
                    doc,
                    center_lat=center_lat,
                    center_lng=center_lng,
                ),
            )
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
