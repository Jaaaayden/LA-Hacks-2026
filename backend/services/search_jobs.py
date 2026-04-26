"""Background search jobs that drive the OfferUp scraper from a shopping list.

A shopping list has N items, each with a `search_query` and `budget_usd`. This
module owns one Chrome session at a time (the persistent profile can't be
shared across processes), iterates the items, and tags each scraped listing
with `list_id` + `item_id` so the Picker can group candidates per slot.
"""

import asyncio
import queue
import sys
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from playwright.async_api import async_playwright

from backend.kitscout.db import listings, search_jobs, shopping_lists
from backend.kitscout.schemas import SearchJob
from backend.services._browser_offerup import launch_logged_in_chrome
from backend.services.listing_store import upsert_scraped_listings
from backend.services.offerup_scraper import _run_one_search


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid Mongo ObjectId: {value}") from exc

# A single local Chrome profile means at most one job in flight per process.
_active_lock = asyncio.Lock()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


async def start_search(shopping_list_id: str) -> dict[str, Any]:
    """Kick off a background scrape for `shopping_list_id`.

    Idempotent for the same list: returns the in-flight job rather than
    starting a duplicate. Raises ValueError("Another search is in progress")
    if a different list is currently being scraped (the API maps that to 409).
    """
    existing = await search_jobs.find_one({"shopping_list_id": shopping_list_id})
    if existing and existing.get("status") in {"pending", "searching"}:
        return _serialize(existing)

    if _active_lock.locked():
        raise ValueError("Another search is in progress")

    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    items = shopping_list.get("items") or []

    job = SearchJob(
        shopping_list_id=shopping_list_id,
        status="pending",
        items_total=len(items),
        started_at=_now(),
    )
    payload = job.model_dump()

    # Replace any prior done/error doc for this list so the unique index is happy.
    await search_jobs.replace_one(
        {"shopping_list_id": shopping_list_id},
        payload,
        upsert=True,
    )

    asyncio.create_task(_run_job(shopping_list_id))

    fresh = await search_jobs.find_one({"shopping_list_id": shopping_list_id})
    return _serialize(fresh or payload)


async def _scrape_all_slots(plan: list[dict], out: "queue.Queue") -> None:
    """Drive a single Chrome session through every slot, streaming events.

    Emits ``("start", index, entry)`` before each slot and
    ``("result", index, entry, scraped)`` after. Runs inside a fresh proactor
    event loop in a worker thread (see ``_scrape_thread_target``); never
    touches motor.
    """
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            for index, entry in enumerate(plan):
                out.put(("start", index, entry))
                try:
                    scraped = await _run_one_search(
                        page,
                        entry["search_query"],
                        max_price=entry.get("max_price"),
                        max_results=15,
                        scrolls=2,
                        capture_images=0,
                        item_type=entry["item_type"],
                        snap_label=f"offerup_{entry['item_type']}",
                    )
                except Exception as exc:
                    print(f"[search-jobs] {entry['item_type']!r} failed: {exc!r}")
                    scraped = []
                out.put(("result", index, entry, scraped))
        finally:
            await context.close()


def _scrape_thread_target(plan: list[dict], out: "queue.Queue") -> None:
    """Thread entry point: gives playwright a proactor loop on Windows.

    uvicorn forces ``WindowsSelectorEventLoopPolicy`` on Python 3.10+, which
    raises ``NotImplementedError`` on ``subprocess_exec`` — the call playwright
    needs to launch Chrome. Running playwright in its own thread with its own
    proactor loop sidesteps this without affecting the FastAPI event loop.
    """
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(_scrape_all_slots(plan, out))
    except Exception as exc:
        out.put(("fatal", exc))
    finally:
        out.put(("done", None))


async def _run_job(shopping_list_id: str) -> None:
    """Background worker. Holds `_active_lock` for the whole Chrome session."""
    async with _active_lock:
        shopping_list = await shopping_lists.find_one(
            {"_id": _object_id(shopping_list_id)}
        )
        if shopping_list is None:
            await search_jobs.update_one(
                {"shopping_list_id": shopping_list_id},
                {
                    "$set": {
                        "status": "error",
                        "error": "Shopping list disappeared before search started.",
                        "finished_at": _now(),
                    }
                },
            )
            return

        hobby = shopping_list.get("hobby")
        query_id = shopping_list.get("query_id")
        items = shopping_list.get("items") or []

        plan = [
            {
                "item_id": item.get("id"),
                "item_type": item.get("item_type") or f"item-{i}",
                "search_query": item.get("search_query")
                or item.get("item_type")
                or f"item-{i}",
                "max_price": int(item["budget_usd"])
                if item.get("budget_usd")
                else None,
            }
            for i, item in enumerate(items)
        ]

        await search_jobs.update_one(
            {"shopping_list_id": shopping_list_id},
            {"$set": {"status": "searching"}},
        )

        out_queue: "queue.Queue" = queue.Queue()
        thread = threading.Thread(
            target=_scrape_thread_target,
            args=(plan, out_queue),
            daemon=True,
        )
        thread.start()

        totals: dict[str, int] = defaultdict(int)
        try:
            while True:
                msg = await asyncio.to_thread(out_queue.get)
                kind = msg[0]

                if kind == "done":
                    break
                if kind == "fatal":
                    raise msg[1]
                if kind == "start":
                    _, index, entry = msg
                    await search_jobs.update_one(
                        {"shopping_list_id": shopping_list_id},
                        {
                            "$set": {
                                "current_item_id": entry["item_id"],
                                "current_item_type": entry["item_type"],
                            }
                        },
                    )
                    continue
                if kind == "result":
                    _, index, entry, scraped = msg
                    counts = await upsert_scraped_listings(
                        scraped,
                        search_query=entry["search_query"],
                        hobby=hobby,
                        item_type=entry["item_type"],
                        query_id=query_id,
                        list_id=shopping_list_id,
                        item_id=entry["item_id"],
                    )
                    for key, value in counts.items():
                        totals[key] += value
                    await search_jobs.update_one(
                        {"shopping_list_id": shopping_list_id},
                        {
                            "$set": {
                                "items_done": index + 1,
                                "counts": dict(totals),
                            }
                        },
                    )

            await asyncio.to_thread(thread.join)
            await search_jobs.update_one(
                {"shopping_list_id": shopping_list_id},
                {
                    "$set": {
                        "status": "done",
                        "finished_at": _now(),
                        "current_item_id": None,
                        "current_item_type": None,
                    }
                },
            )
        except Exception as exc:
            await search_jobs.update_one(
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
    doc = await search_jobs.find_one({"shopping_list_id": shopping_list_id})
    return _serialize(doc) if doc else None


def _shape_for_picker(doc: dict[str, Any]) -> dict[str, Any]:
    location = doc.get("location") or {}
    location_raw = location.get("raw") if isinstance(location, dict) else None
    return {
        "listing_id": doc.get("platform_id"),
        "title": doc.get("title") or "",
        "price_usd": doc.get("price_usd"),
        "list_price_usd": None,
        "image_url": doc.get("image_url"),
        "condition": doc.get("condition") or "good",
        "location": location_raw or "",
        "url": doc.get("url"),
        "rating": None,
        "blurb": None,
        "is_top_match": False,
    }


async def get_candidates(shopping_list_id: str) -> dict[str, list[dict[str, Any]]]:
    """Return listings for a shopping list grouped by `item_id`, price ascending."""
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    cursor = listings.find({"list_id": shopping_list_id}).sort("price_usd", 1)
    async for doc in cursor:
        item_id = doc.get("item_id")
        if not item_id:
            continue
        grouped[item_id].append(_shape_for_picker(doc))
    return dict(grouped)
