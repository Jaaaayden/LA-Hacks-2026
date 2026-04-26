"""Background listing search orchestration for shopping lists.

This module does not scrape OfferUp directly. It coordinates the GraphQL scraper
for each shopping-list item, persists listings, and exposes lightweight job
status for the frontend to poll while candidates stream into Mongo.
"""

import asyncio
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
from backend.services.listing_store import upsert_scraped_listings
from backend.services.listing_store import parse_platform_id
from backend.services.offerup_scraper import search_offerup

DEFAULT_RESULTS_PER_ITEM = 30

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
        return None
    location = intent.get("location")
    if isinstance(location, str):
        return location
    if isinstance(location, dict):
        raw = location.get("raw")
        if raw:
            return str(raw)
        city = location.get("city")
        state = location.get("state")
        parts = [str(part) for part in (city, state) if part]
        if parts:
            return ", ".join(parts)
    return None


def _candidate_shape(doc: dict[str, Any]) -> dict[str, Any]:
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
        "is_top_match": False,
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
            location = _location_from_intent(
                query_doc.get("parsed_intent") if query_doc else None
            )

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
                    location=location,
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
    """Return stored candidates grouped by shopping-list item id."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cursor = listings.find({"list_id": shopping_list_id}).sort("price_usd", 1)
    async for doc in cursor:
        item_id = doc.get("item_id")
        if not item_id:
            continue
        grouped[item_id].append(_candidate_shape(doc))
    return dict(grouped)
