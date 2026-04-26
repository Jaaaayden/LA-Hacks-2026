"""Manages "items in flight" — listings the user selected for negotiation.

Flow:
1. `add_to_bargain` creates BargainItem docs (status="queued") and fires a
   background thread to send the opening message on OfferUp.
2. The playwright thread opens each listing URL, clicks Message, types the
   Claude-generated opener, and hits Enter. Same proactor-thread pattern as
   listing_search so uvicorn's selector loop is never asked to spawn a
   subprocess.
3. `get_bargain_items` returns all items for a shopping list so ActiveSearch
   can show real data.
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from playwright.async_api import Page, async_playwright

from backend.kitscout.db import bargain_items, listings, shopping_lists
from backend.kitscout.schemas import BargainItem
from backend.services.gen_negotiation_message import gen_negotiation_message


def _object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except Exception as exc:
        raise ValueError(f"Invalid Mongo ObjectId: {value}") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _serialize(doc: dict[str, Any]) -> dict[str, Any]:
    out = dict(doc)
    if "_id" in out:
        out["_id"] = str(out["_id"])
    return out


# ──────────────────────────────────────────────────────────────────────────────
# OfferUp message sending
# ──────────────────────────────────────────────────────────────────────────────

async def _send_message_on_offerup(page: Page, listing_url: str, message: str) -> None:
    """Navigate to a listing page and send `message` via OfferUp's chat UI."""
    await page.goto(listing_url, wait_until="domcontentloaded", timeout=60_000)
    # Wait for React to hydrate — networkidle is more reliable than a fixed sleep.
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await asyncio.sleep(2)

    # Dismiss any popup overlays (cookie banners, app-download prompts, etc.).
    for sel in (
        '[aria-label="Close"]',
        '[aria-label="close"]',
        'button:has-text("Got it")',
        'button:has-text("No thanks")',
        'button:has-text("Not now")',
    ):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click()
                await asyncio.sleep(0.3)
        except Exception:
            pass

    # Scroll so any sticky CTA bar becomes visible.
    await page.mouse.wheel(0, 400)
    await asyncio.sleep(0.5)

    # Take a debug screenshot so we can see the page state.
    from pathlib import Path
    debug_dir = Path("scraper/output/debug")
    debug_dir.mkdir(parents=True, exist_ok=True)
    pid = listing_url.rstrip("/").split("/")[-1]
    await page.screenshot(path=str(debug_dir / f"msg_before_{pid[:8]}.png"))

    # --- Find and click the Message button ---
    # Try Playwright's role/text API first (more resilient to CSS changes).
    message_btn_found = False
    for name in ("Message", "Chat", "Send message", "Message seller"):
        try:
            btn = page.get_by_role("button", name=name, exact=False)
            if await btn.first.is_visible(timeout=2000):
                await btn.first.click()
                message_btn_found = True
                await asyncio.sleep(2)
                break
        except Exception:
            pass
        try:
            lnk = page.get_by_role("link", name=name, exact=False)
            if await lnk.first.is_visible(timeout=1000):
                await lnk.first.click()
                message_btn_found = True
                await asyncio.sleep(2)
                break
        except Exception:
            pass

    # CSS selector fallbacks.
    if not message_btn_found:
        for sel in [
            '[data-testid*="message"]',
            '[data-testid*="chat"]',
            '[aria-label*="Message" i]',
            'button:has-text("Message")',
            'a:has-text("Message")',
        ]:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=1500):
                    await btn.click()
                    message_btn_found = True
                    await asyncio.sleep(2)
                    break
            except Exception:
                continue

    if not message_btn_found:
        raise RuntimeError(
            f"Message button not found on {listing_url} — "
            "check scraper/output/debug/msg_before_*.png"
        )

    # After clicking, wait for the chat input to appear.
    try:
        await page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    await asyncio.sleep(1)

    # --- Find the text input and type the message ---
    for sel in [
        'textarea[placeholder*="message" i]',
        'textarea[placeholder*="Type" i]',
        'textarea[aria-label*="message" i]',
        '[data-testid*="message-input"]',
        '[data-testid*="compose"]',
        'div[contenteditable="true"]',
        'textarea',
    ]:
        try:
            inp = page.locator(sel).last
            if await inp.is_visible(timeout=2500):
                await inp.click()
                await inp.fill(message)
                await asyncio.sleep(0.4)
                # Try a Send button; fall back to Enter.
                sent = False
                for send_sel in [
                    'button:has-text("Send")',
                    '[aria-label*="Send" i]',
                    '[data-testid*="send"]',
                ]:
                    try:
                        send_btn = page.locator(send_sel).first
                        if await send_btn.is_visible(timeout=1500):
                            await send_btn.click()
                            sent = True
                            break
                    except Exception:
                        continue
                if not sent:
                    await inp.press("Enter")
                await asyncio.sleep(1)
                await page.screenshot(path=str(debug_dir / f"msg_after_{pid[:8]}.png"))
                return
        except Exception:
            continue

    raise RuntimeError(f"Could not find message input on {listing_url}")


# ──────────────────────────────────────────────────────────────────────────────
# Background messaging — playwright thread
# ──────────────────────────────────────────────────────────────────────────────

async def _message_all_items(items_data: list[dict], out: queue.Queue) -> None:
    """Drive a single Chrome session to send one opening message per item."""
    from backend.services._browser_offerup import launch_logged_in_chrome

    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            for item_data in items_data:
                out.put(("start", item_data["listing_id"]))
                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        gen_negotiation_message,
                        item_data["title"],
                        item_data["price_usd"],
                        item_data["target_price_usd"],
                        [],
                    )
                    message = result.get("message") or ""
                    action = result.get("action", "send")

                    if action != "give_up" and message:
                        await _send_message_on_offerup(page, item_data["url"], message)
                        out.put(("sent", item_data["listing_id"], message))
                    else:
                        out.put(("gave_up", item_data["listing_id"]))
                except Exception as exc:
                    print(f"[bargain] messaging {item_data['listing_id']!r} failed: {exc!r}")
                    out.put(("error", item_data["listing_id"], str(exc)))
        finally:
            await context.close()


def _message_thread_target(items_data: list[dict], out: queue.Queue) -> None:
    """Thread entry: run playwright in a fresh proactor loop on Windows."""
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(_message_all_items(items_data, out))
    except Exception as exc:
        out.put(("fatal", exc))
    finally:
        out.put(("done", None))


async def _run_messaging(items_data: list[dict]) -> None:
    """Async background task: drive the messaging thread and write results to Mongo."""
    out_queue: queue.Queue = queue.Queue()
    thread = threading.Thread(
        target=_message_thread_target,
        args=(items_data, out_queue),
        daemon=True,
    )
    thread.start()

    try:
        while True:
            msg = await asyncio.to_thread(out_queue.get)
            kind = msg[0]

            if kind == "done":
                break
            if kind == "fatal":
                # Log but don't propagate — this is a fire-and-forget task.
                print(f"[bargain] messaging thread fatal: {msg[1]!r}")
                break
            if kind == "start":
                listing_id = msg[1]
                await bargain_items.update_one(
                    {"listing_id": listing_id},
                    {"$set": {"status": "messaging", "updated_at": _now()}},
                )
            elif kind == "sent":
                listing_id, message = msg[1], msg[2]
                await bargain_items.update_one(
                    {"listing_id": listing_id},
                    {
                        "$set": {
                            "status": "messaging",
                            "last_message": message,
                            "updated_at": _now(),
                        },
                        "$push": {
                            "conversation": {"role": "negotiator", "content": message}
                        },
                    },
                )
            elif kind == "gave_up":
                listing_id = msg[1]
                await bargain_items.update_one(
                    {"listing_id": listing_id},
                    {"$set": {"status": "gave_up", "updated_at": _now()}},
                )
            elif kind == "error":
                listing_id, error = msg[1], msg[2]
                await bargain_items.update_one(
                    {"listing_id": listing_id},
                    {
                        "$set": {
                            "status": "error",
                            "error": error,
                            "updated_at": _now(),
                        }
                    },
                )
    finally:
        await asyncio.to_thread(thread.join)


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

async def add_to_bargain(
    shopping_list_id: str,
    item_id: str,
    listing_ids: list[str],
) -> list[dict[str, Any]]:
    """Persist selected listings as BargainItems and fire opening messages.

    Idempotent: if a listing_id is already in bargain_items for this list,
    the existing doc is returned without creating a duplicate or re-messaging.
    """
    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    item_meta = next(
        (i for i in (shopping_list.get("items") or []) if i.get("id") == item_id),
        None,
    )
    target_price = float(item_meta.get("budget_usd") or 0) if item_meta else 0.0
    item_type = (item_meta.get("item_type") or "item") if item_meta else "item"

    # Fetch the listing docs so we have title / price / url.
    listing_docs: list[dict] = await listings.find(
        {"platform_id": {"$in": listing_ids}, "list_id": shopping_list_id}
    ).to_list(None)
    listing_map = {d["platform_id"]: d for d in listing_docs}

    now = _now()
    created: list[dict[str, Any]] = []
    new_items_data: list[dict] = []

    for lid in listing_ids:
        doc = listing_map.get(lid)
        if doc is None:
            continue

        location = doc.get("location") or {}
        location_raw = (
            location.get("raw") if isinstance(location, dict) else None
        )

        bargain_doc = BargainItem(
            shopping_list_id=shopping_list_id,
            item_id=item_id,
            item_type=item_type,
            listing_id=lid,
            title=doc.get("title") or "",
            price_usd=float(doc.get("price_usd") or 0),
            target_price_usd=target_price,
            url=doc.get("url") or "",
            image_url=doc.get("image_url"),
            location_raw=location_raw,
            added_at=now,
            updated_at=now,
        )
        payload = bargain_doc.model_dump()

        result = await bargain_items.update_one(
            {"shopping_list_id": shopping_list_id, "listing_id": lid},
            {"$setOnInsert": payload},
            upsert=True,
        )
        # Only queue the message for newly inserted items.
        if result.upserted_id is not None:
            new_items_data.append({
                "listing_id": lid,
                "title": bargain_doc.title,
                "price_usd": bargain_doc.price_usd,
                "target_price_usd": bargain_doc.target_price_usd,
                "url": bargain_doc.url,
            })

        fresh = await bargain_items.find_one(
            {"shopping_list_id": shopping_list_id, "listing_id": lid}
        )
        if fresh:
            created.append(_serialize(fresh))

    if new_items_data:
        asyncio.create_task(_run_messaging(new_items_data))

    return created


async def get_bargain_items(shopping_list_id: str) -> list[dict[str, Any]]:
    cursor = bargain_items.find({"shopping_list_id": shopping_list_id}).sort("added_at", 1)
    return [_serialize(doc) async for doc in cursor]
