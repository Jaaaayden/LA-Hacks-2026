"""Manage "items in flight" and OfferUp negotiation automation.

Flow:
1. `add_to_bargain` stores selected listings as BargainItem docs.
2. New inserts trigger background opening-message sends on OfferUp.
3. A minute poller checks for seller replies and can auto-send the next step
   via the negotiator model.
"""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bson import ObjectId
from playwright.async_api import Page, async_playwright

from backend.kitscout.db import bargain_items, listings, shopping_lists
from backend.kitscout.schemas import BargainItem
from backend.services.gen_negotiation_message import gen_negotiation_message
from backend.services.offerup_message_reader import check_offerup_thread_messages
from backend.services.seller_reply_enricher import enrich_listing_from_seller_reply

MESSAGE_PAGE_CONCURRENCY = 3
NEGOTIATION_POLL_INTERVAL_SECONDS = 60
NEGOTIATION_TARGET_DISCOUNT_RATIO = 0.18

_OFFERUP_BROWSER_LOCK = asyncio.Lock()
_NEGOTIATION_POLL_TASKS: dict[str, asyncio.Task[None]] = {}


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


def _listing_token(listing_url: str) -> str:
    return listing_url.rstrip("/").split("/")[-1][:8]


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _effective_target_price(asking_price_usd: float, target_price_usd: float) -> float:
    asking = max(0.0, float(asking_price_usd or 0))
    budget = max(0.0, float(target_price_usd or 0))

    if asking <= 0:
        return round(budget, 2)

    discounted_target = asking * (1 - NEGOTIATION_TARGET_DISCOUNT_RATIO)
    target = discounted_target
    if budget > 0:
        target = min(target, budget)

    if target >= asking and asking >= 5:
        target = asking - 1

    return round(max(0.0, target), 2)


def _seller_question_text(question: Any) -> str:
    if isinstance(question, dict):
        return str(question.get("question") or "").strip()
    return str(question or "").strip()


def _build_seller_detail_message(item_data: dict[str, Any]) -> str:
    """Ask only for important missing listing details before negotiation."""
    seller_questions = [
        _seller_question_text(question)
        for question in (item_data.get("seller_questions") or [])
    ]
    questions = [question for question in seller_questions if question][:3]
    if not questions:
        missing_fields = [
            str(field).replace("_", " ").strip()
            for field in (item_data.get("missing_fields") or [])
            if str(field or "").strip()
        ][:3]
        if missing_fields:
            fields = ", ".join(missing_fields)
            questions = [f"Could you confirm the {fields}?"]

    if not questions:
        questions = [
            "Could you confirm the condition and whether there are any issues I should know about?"
        ]

    joined = " ".join(questions)
    return f"Hi, I'm interested in this. {joined}"


def _merge_listing_attributes(
    existing: list[dict[str, Any]],
    new_attributes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in [*existing, *new_attributes]:
        if not isinstance(row, dict):
            continue
        key = str(row.get("key") or "").strip()
        value = str(row.get("value") or "").strip()
        if not key or not value:
            continue
        dedupe_key = (key.lower(), value.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(dict(row))
    return merged


def _field_satisfied(field: Any, satisfied_fields: list[str]) -> bool:
    normalized = _normalize_text(str(field or "").replace("_", " "))
    if not normalized:
        return True
    for satisfied in satisfied_fields:
        other = _normalize_text(str(satisfied or "").replace("_", " "))
        if other and (normalized == other or normalized in other or other in normalized):
            return True
    return False


async def _prepare_offerup_chat(
    page: Page,
    listing_url: str,
    *,
    debug_snapshot: bool,
) -> None:
    """Navigate to listing page and open the OfferUp chat composer."""
    await page.goto(listing_url, wait_until="domcontentloaded", timeout=60_000)
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except Exception:
        pass
    await asyncio.sleep(1.5)

    # Some OfferUp navigations preserve scroll position in the SPA shell.
    # Force top before trying to find message CTAs.
    with suppress(Exception):
        await page.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(0.3)

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

    if debug_snapshot:
        debug_dir = Path("scraper/output/debug")
        debug_dir.mkdir(parents=True, exist_ok=True)
        await page.screenshot(
            path=str(debug_dir / f"msg_before_{_listing_token(listing_url)}.png")
        )

    async def _click_locator_first(loc) -> bool:
        try:
            count = await loc.count()
            if count == 0:
                return False
            target = loc.first
            with suppress(Exception):
                await target.scroll_into_view_if_needed()
            await target.click(timeout=4_000)
            await asyncio.sleep(1.2)
            return True
        except Exception:
            return False

    message_btn_found = False
    for name in (
        "Ask",
        "Message",
        "Message seller",
        "Send message",
        "Contact seller",
        "Make offer",
        "Chat",
    ):
        try:
            btn = page.get_by_role("button", name=name, exact=False)
            if await _click_locator_first(btn):
                message_btn_found = True
                break
        except Exception:
            pass
        try:
            lnk = page.get_by_role("link", name=name, exact=False)
            if await _click_locator_first(lnk):
                message_btn_found = True
                break
        except Exception:
            pass

    if not message_btn_found:
        for sel in (
            '[data-testid*="ask"]',
            '[data-testid*="message"]',
            '[data-testid*="chat"]',
            'button:has-text("Ask")',
            '[aria-label*="Message" i]',
            '[aria-label*="Ask" i]',
            'button:has-text("Message")',
            'button:has-text("Contact seller")',
            'button:has-text("Make offer")',
            'a:has-text("Message")',
        ):
            try:
                btn = page.locator(sel).first
                if await _click_locator_first(btn):
                    message_btn_found = True
                    break
            except Exception:
                continue

    if not message_btn_found:
        # JS fallback: scan likely controls and click first messaging CTA text.
        try:
            clicked = await page.evaluate(
                """
                () => {
                  const wanted = ["ask", "message", "message seller", "send message", "contact seller", "make offer", "chat"];
                  const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
                  for (const node of nodes) {
                    const text = ((node.innerText || node.textContent || "").trim()).toLowerCase();
                    if (!text) continue;
                    if (!wanted.some((w) => text.includes(w))) continue;
                    node.scrollIntoView({ block: "center", behavior: "instant" });
                    node.click();
                    return true;
                  }
                  return false;
                }
                """
            )
            if clicked:
                message_btn_found = True
                await asyncio.sleep(1.2)
        except Exception:
            pass

    if not message_btn_found:
        # Offer a more diagnostic error when auth wall is likely.
        body_text = ""
        with suppress(Exception):
            body_text = (await page.locator("body").inner_text())[:5000].lower()
        if "log in" in body_text or "sign in" in body_text:
            raise RuntimeError(
                f"Messaging unavailable on {listing_url} - OfferUp appears to require login."
            )
        raise RuntimeError(
            f"Message button not found on {listing_url} - "
            "check scraper/output/debug/msg_before_*.png"
        )

    try:
        await page.wait_for_load_state("networkidle", timeout=8_000)
    except Exception:
        pass
    await asyncio.sleep(1)


async def _fill_and_send_chat_message(
    page: Page,
    listing_url: str,
    message: str,
    *,
    debug_snapshot: bool,
) -> None:
    """Type a message in the already-open OfferUp composer and send it."""
    for sel in (
        'textarea[placeholder*="message" i]',
        'textarea[placeholder*="Type" i]',
        'textarea[aria-label*="message" i]',
        '[data-testid*="message-input"]',
        '[data-testid*="compose"]',
        'div[contenteditable="true"]',
        "textarea",
    ):
        try:
            inp = page.locator(sel).last
            if await inp.is_visible(timeout=2500):
                await inp.click()
                await inp.fill(message)
                await asyncio.sleep(0.4)

                sent = False
                for send_sel in (
                    'button:has-text("Send")',
                    '[aria-label*="Send" i]',
                    '[data-testid*="send"]',
                ):
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

                if debug_snapshot:
                    debug_dir = Path("scraper/output/debug")
                    debug_dir.mkdir(parents=True, exist_ok=True)
                    await page.screenshot(
                        path=str(
                            debug_dir / f"msg_after_{_listing_token(listing_url)}.png"
                        )
                    )
                return
        except Exception:
            continue

    raise RuntimeError(f"Could not find message input on {listing_url}")


async def _send_message_on_offerup(page: Page, listing_url: str, message: str) -> str:
    await _prepare_offerup_chat(page, listing_url, debug_snapshot=True)
    await _fill_and_send_chat_message(
        page,
        listing_url,
        message,
        debug_snapshot=True,
    )
    return page.url


async def _extract_chat_candidates(page: Page) -> list[dict[str, str]]:
    """Best-effort extraction of recent chat text blocks from the message panel."""
    raw = await page.evaluate(
        """
        () => {
          const composer = document.querySelector(
            'textarea[placeholder*="message" i], textarea[aria-label*="message" i], ' +
            'input[placeholder*="message" i], input[aria-label*="message" i], ' +
            '[contenteditable="true"][aria-label*="message" i], textarea, [role="textbox"]'
          );

          let scope = document.body;
          if (composer) {
            let node = composer;
            for (let i = 0; i < 8 && node?.parentElement; i += 1) {
              node = node.parentElement;
            }
            if (node) scope = node;
          }

          const getRole = (el) => {
            const label = (
              el.getAttribute("aria-label") ||
              el.closest("[aria-label]")?.getAttribute("aria-label") ||
              ""
            ).toLowerCase();
            if (label.includes("you")) return "negotiator";
            if (label.includes("seller") || label.includes("them") || label.includes("other")) {
              return "seller";
            }
            return "unknown";
          };

          const out = [];
          const seen = new Set();
          const nodes = scope.querySelectorAll(
            '[data-testid*="message" i], [class*="message" i], [class*="chat" i], li, p, span, div'
          );

          for (const node of nodes) {
            const text = (node.innerText || "").replace(/\\s+/g, " ").trim();
            if (!text || text.length < 2 || text.length > 280) continue;
            const lower = text.toLowerCase();
            if (
              lower === "send" ||
              lower.includes("type a message") ||
              lower.includes("message seller") ||
              lower.includes("make offer")
            ) {
              continue;
            }

            const role = getRole(node);
            const key = `${role}|${lower}`;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({ text, role });
          }

          return out.slice(-120);
        }
        """
    )
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        role = str(row.get("role") or "unknown")
        if text:
            out.append({"text": text, "role": role})
    return out


def _pick_new_seller_reply(
    candidates: list[dict[str, str]],
    conversation: list[dict[str, str]],
    listing_title: str,
) -> str | None:
    known = {
        _normalize_text(turn.get("content", ""))
        for turn in conversation
        if turn.get("content")
    }
    ignore_exact = {
        _normalize_text(listing_title),
        "send",
        "message",
        "message seller",
        "type a message",
        "make offer",
    }

    for row in reversed(candidates):
        text = row.get("text", "")
        role = row.get("role", "unknown")
        normalized = _normalize_text(text)
        if not normalized:
            continue
        if normalized in known or normalized in ignore_exact:
            continue
        if role == "negotiator":
            continue
        if role == "unknown" and "$" not in text and len(text.split()) < 3:
            continue
        return text
    return None


async def _read_new_seller_reply_on_offerup(page: Page, item_data: dict[str, Any]) -> str | None:
    await _prepare_offerup_chat(page, item_data["url"], debug_snapshot=False)
    candidates = await _extract_chat_candidates(page)
    return _pick_new_seller_reply(
        candidates,
        item_data.get("conversation") or [],
        item_data.get("title") or "",
    )


async def _message_all_items(items_data: list[dict[str, Any]], out: queue.Queue) -> None:
    """Drive one Chrome session and send seller detail questions."""
    from backend.services._browser_offerup import launch_logged_in_chrome

    if not items_data:
        return

    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            concurrency = max(1, min(MESSAGE_PAGE_CONCURRENCY, len(items_data)))
            semaphore = asyncio.Semaphore(concurrency)

            async def send_one(item_data: dict[str, Any]) -> None:
                listing_id = item_data["listing_id"]
                out.put(("start", listing_id))
                async with semaphore:
                    page = await context.new_page()
                    try:
                        message = _build_seller_detail_message(item_data)
                        thread_url = await _send_message_on_offerup(
                            page,
                            item_data["url"],
                            message,
                        )
                        out.put(("sent", listing_id, message, thread_url))
                    except Exception as exc:
                        print(f"[bargain] opening message failed for {listing_id!r}: {exc!r}")
                        out.put(("error", listing_id, str(exc)))
                    finally:
                        await page.close()

            await asyncio.gather(*(send_one(item) for item in items_data))
        finally:
            await context.close()


def _message_thread_target(items_data: list[dict[str, Any]], out: queue.Queue) -> None:
    """Thread entry: run playwright in a fresh proactor loop on Windows."""
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(_message_all_items(items_data, out))
    except Exception as exc:
        out.put(("fatal", exc))
    finally:
        out.put(("done", None))


async def _run_messaging(items_data: list[dict[str, Any]]) -> None:
    """Background task for opening messages; serialized around shared profile."""
    if not items_data:
        return

    async with _OFFERUP_BROWSER_LOCK:
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
                    print(f"[bargain] messaging thread fatal: {msg[1]!r}")
                    break
                if kind == "start":
                    listing_id = msg[1]
                    await bargain_items.update_one(
                        {"listing_id": listing_id},
                        {"$set": {"status": "selected", "updated_at": _now()}},
                    )
                elif kind == "sent":
                    listing_id, message, thread_url = msg[1], msg[2], msg[3]
                    await bargain_items.update_one(
                        {"listing_id": listing_id},
                        {
                            "$set": {
                                "status": "questions_sent",
                                "last_message": message,
                                "thread_url": thread_url,
                                "updated_at": _now(),
                            },
                            "$push": {
                                "conversation": {"role": "buyer", "content": message}
                            },
                        },
                    )
                elif kind == "agreed":
                    listing_id, message, thread_url = msg[1], msg[2], msg[3]
                    await bargain_items.update_one(
                        {"listing_id": listing_id},
                        {
                            "$set": {
                                "status": "agreed",
                                "last_message": message,
                                "thread_url": thread_url,
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


async def _poll_and_negotiate_items(items_data: list[dict[str, Any]], out: queue.Queue) -> None:
    """Check each active thread for new seller messages and react via negotiator."""
    from backend.services._browser_offerup import launch_logged_in_chrome

    if not items_data:
        return

    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            concurrency = max(1, min(MESSAGE_PAGE_CONCURRENCY, len(items_data)))
            semaphore = asyncio.Semaphore(concurrency)
            loop = asyncio.get_running_loop()

            async def poll_one(item_data: dict[str, Any]) -> None:
                listing_id = item_data["listing_id"]
                async with semaphore:
                    page = await context.new_page()
                    try:
                        seller_reply = await _read_new_seller_reply_on_offerup(page, item_data)
                        if not seller_reply:
                            return
                        out.put(("seller_reply", listing_id, seller_reply))

                        conversation = list(item_data.get("conversation") or [])
                        conversation.append({"role": "seller", "content": seller_reply})
                        asking_price = float(item_data["price_usd"])
                        effective_target = _effective_target_price(
                            asking_price,
                            float(item_data["target_price_usd"]),
                        )
                        result = await loop.run_in_executor(
                            None,
                            gen_negotiation_message,
                            item_data["title"],
                            asking_price,
                            effective_target,
                            conversation,
                        )
                        action = result.get("action", "give_up")
                        message = result.get("message") or ""

                        if action == "give_up" or not message:
                            out.put(("gave_up", listing_id))
                            return

                        await _fill_and_send_chat_message(
                            page,
                            item_data["url"],
                            message,
                            debug_snapshot=False,
                        )
                        if action == "accept":
                            out.put(("agreed", listing_id, message))
                        else:
                            out.put(("sent", listing_id, message))
                    except Exception as exc:
                        print(f"[bargain] poll+negotiate failed for {listing_id!r}: {exc!r}")
                        out.put(("error", listing_id, str(exc)))
                    finally:
                        await page.close()

            await asyncio.gather(*(poll_one(item) for item in items_data))
        finally:
            await context.close()


def _poll_thread_target(items_data: list[dict[str, Any]], out: queue.Queue) -> None:
    try:
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        asyncio.run(_poll_and_negotiate_items(items_data, out))
    except Exception as exc:
        out.put(("fatal", exc))
    finally:
        out.put(("done", None))


async def _run_poll_cycle(shopping_list_id: str) -> None:
    docs = await bargain_items.find(
        {
            "shopping_list_id": shopping_list_id,
            "status": "negotiating",
        }
    ).to_list(None)
    if not docs:
        return

    items_data: list[dict[str, Any]] = []
    for doc in docs:
        url = str(doc.get("url") or "")
        listing_id = str(doc.get("listing_id") or "")
        if not url or not listing_id:
            continue
        items_data.append(
            {
                "listing_id": listing_id,
                "title": str(doc.get("title") or ""),
                "price_usd": float(doc.get("price_usd") or 0),
                "target_price_usd": _effective_target_price(
                    float(doc.get("price_usd") or 0),
                    float(doc.get("target_price_usd") or 0),
                ),
                "url": url,
                "conversation": list(doc.get("conversation") or []),
            }
        )

    if not items_data:
        return

    async with _OFFERUP_BROWSER_LOCK:
        out_queue: queue.Queue = queue.Queue()
        thread = threading.Thread(
            target=_poll_thread_target,
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
                    print(f"[bargain] poll thread fatal: {msg[1]!r}")
                    break
                if kind == "seller_reply":
                    listing_id, seller_reply = msg[1], msg[2]
                    await bargain_items.update_one(
                        {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
                        {
                            "$set": {
                                "last_seller_message": seller_reply,
                                "updated_at": _now(),
                            },
                            "$push": {
                                "conversation": {"role": "seller", "content": seller_reply}
                            },
                        },
                    )
                elif kind == "sent":
                    listing_id, message = msg[1], msg[2]
                    await bargain_items.update_one(
                        {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
                        {
                            "$set": {
                                "status": "negotiating",
                                "last_message": message,
                                "updated_at": _now(),
                            },
                            "$push": {
                                "conversation": {"role": "negotiator", "content": message}
                            },
                        },
                    )
                elif kind == "agreed":
                    listing_id, message = msg[1], msg[2]
                    await bargain_items.update_one(
                        {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
                        {
                            "$set": {
                                "status": "agreed",
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
                        {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
                        {"$set": {"status": "gave_up", "updated_at": _now()}},
                    )
                elif kind == "error":
                    listing_id, error = msg[1], msg[2]
                    await bargain_items.update_one(
                        {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
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


async def _negotiation_poll_loop(shopping_list_id: str) -> None:
    try:
        while True:
            await _run_poll_cycle(shopping_list_id)
            await asyncio.sleep(NEGOTIATION_POLL_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"[bargain] poll loop crashed for {shopping_list_id}: {exc!r}")
    finally:
        task = _NEGOTIATION_POLL_TASKS.get(shopping_list_id)
        if task is asyncio.current_task():
            _NEGOTIATION_POLL_TASKS.pop(shopping_list_id, None)


def _ensure_negotiation_poller(shopping_list_id: str) -> bool:
    existing = _NEGOTIATION_POLL_TASKS.get(shopping_list_id)
    if existing and not existing.done():
        return False
    _NEGOTIATION_POLL_TASKS[shopping_list_id] = asyncio.create_task(
        _negotiation_poll_loop(shopping_list_id)
    )
    return True


async def start_negotiation_poller(shopping_list_id: str) -> dict[str, Any]:
    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    started = _ensure_negotiation_poller(shopping_list_id)
    return {
        "shopping_list_id": shopping_list_id,
        "running": True,
        "started": started,
        "interval_seconds": NEGOTIATION_POLL_INTERVAL_SECONDS,
    }


async def stop_negotiation_poller(shopping_list_id: str) -> dict[str, Any]:
    task = _NEGOTIATION_POLL_TASKS.pop(shopping_list_id, None)
    if task is None:
        return {
            "shopping_list_id": shopping_list_id,
            "running": False,
            "stopped": False,
            "interval_seconds": NEGOTIATION_POLL_INTERVAL_SECONDS,
        }

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    return {
        "shopping_list_id": shopping_list_id,
        "running": False,
        "stopped": True,
        "interval_seconds": NEGOTIATION_POLL_INTERVAL_SECONDS,
    }


async def get_negotiation_poller_status(shopping_list_id: str) -> dict[str, Any]:
    task = _NEGOTIATION_POLL_TASKS.get(shopping_list_id)
    running = bool(task and not task.done())
    return {
        "shopping_list_id": shopping_list_id,
        "running": running,
        "interval_seconds": NEGOTIATION_POLL_INTERVAL_SECONDS,
    }


async def add_to_bargain(
    shopping_list_id: str,
    item_id: str,
    listing_ids: list[str],
) -> list[dict[str, Any]]:
    """Persist selected listings and send pre-negotiation detail questions.

    Idempotent: if a listing_id is already in bargain_items for this list,
    the existing doc is returned without creating a duplicate or re-contacting.
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

    listing_docs: list[dict[str, Any]] = await listings.find(
        {"platform_id": {"$in": listing_ids}, "list_id": shopping_list_id}
    ).to_list(None)
    listing_map = {str(doc["platform_id"]): doc for doc in listing_docs}

    now = _now()
    created: list[dict[str, Any]] = []
    new_items_data: list[dict[str, Any]] = []

    for listing_id in listing_ids:
        doc = listing_map.get(str(listing_id))
        if doc is None:
            continue

        location = doc.get("location") or {}
        location_raw = location.get("raw") if isinstance(location, dict) else None
        asking_price = float(doc.get("price_usd") or 0)
        effective_target = _effective_target_price(asking_price, target_price)

        bargain_doc = BargainItem(
            shopping_list_id=shopping_list_id,
            item_id=item_id,
            item_type=item_type,
            listing_id=str(listing_id),
            title=str(doc.get("title") or ""),
            price_usd=asking_price,
            target_price_usd=effective_target,
            url=str(doc.get("url") or ""),
            image_url=doc.get("image_url"),
            location_raw=location_raw,
            added_at=now,
            updated_at=now,
        )
        payload = bargain_doc.model_dump()

        result = await bargain_items.update_one(
            {"shopping_list_id": shopping_list_id, "listing_id": str(listing_id)},
            {"$setOnInsert": payload},
            upsert=True,
        )
        if result.upserted_id is not None:
            new_items_data.append(
                {
                    "listing_id": str(listing_id),
                    "title": bargain_doc.title,
                    "price_usd": bargain_doc.price_usd,
                    "target_price_usd": bargain_doc.target_price_usd,
                    "url": bargain_doc.url,
                    "seller_questions": list(doc.get("seller_questions") or []),
                    "missing_fields": list(doc.get("missing_fields") or []),
                }
            )

        fresh = await bargain_items.find_one(
            {"shopping_list_id": shopping_list_id, "listing_id": str(listing_id)}
        )
        if fresh:
            created.append(_serialize(fresh))

    if new_items_data:
        asyncio.create_task(_run_messaging(new_items_data))

    return created


async def get_bargain_items(shopping_list_id: str) -> list[dict[str, Any]]:
    cursor = bargain_items.find({"shopping_list_id": shopping_list_id}).sort("added_at", 1)
    return [_serialize(doc) async for doc in cursor]


async def poll_bargain_messages(shopping_list_id: str) -> dict[str, Any]:
    """Read stored OfferUp threads and persist new seller replies without negotiating."""
    shopping_list = await shopping_lists.find_one({"_id": _object_id(shopping_list_id)})
    if shopping_list is None:
        raise ValueError(f"Shopping list not found: {shopping_list_id}")

    docs = await bargain_items.find(
        {
            "shopping_list_id": shopping_list_id,
            "status": {"$in": ["questions_sent", "ready_to_negotiate", "negotiating"]},
        }
    ).to_list(None)

    checked: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for doc in docs:
        listing_id = str(doc.get("listing_id") or "")
        thread_url = str(doc.get("thread_url") or "")
        if not listing_id:
            continue
        if not thread_url:
            skipped.append(
                {
                    "listing_id": listing_id,
                    "reason": "missing_thread_url",
                }
            )
            continue

        known_messages = [
            str(turn.get("content") or "")
            for turn in (doc.get("conversation") or [])
            if isinstance(turn, dict) and turn.get("content")
        ]
        result = await check_offerup_thread_messages(
            thread_url,
            known_messages=known_messages,
        )
        checked.append(
            {
                "listing_id": listing_id,
                "thread_url": thread_url,
                "has_new_message": bool(result.get("has_new_message")),
                "latest_message": result.get("latest_message"),
            }
        )

        seller_reply = result.get("latest_message")
        if not seller_reply:
            continue

        listing_doc = await listings.find_one(
            {"platform_id": listing_id, "list_id": shopping_list_id}
        )
        enrichment: dict[str, Any] = {
            "extracted_attributes": [],
            "satisfied_missing_fields": [],
            "notes": "",
        }
        if listing_doc:
            enrichment = enrich_listing_from_seller_reply(
                listing=listing_doc,
                bargain_item=doc,
                seller_reply=str(seller_reply),
            )
            satisfied_fields = list(enrichment.get("satisfied_missing_fields") or [])
            merged_attributes = _merge_listing_attributes(
                list(listing_doc.get("extracted_attributes") or []),
                list(enrichment.get("extracted_attributes") or []),
            )
            remaining_missing_fields = [
                field
                for field in (listing_doc.get("missing_fields") or [])
                if not _field_satisfied(field, satisfied_fields)
            ]
            remaining_questions = [
                question
                for question in (listing_doc.get("seller_questions") or [])
                if not (
                    isinstance(question, dict)
                    and _field_satisfied(question.get("field"), satisfied_fields)
                )
            ]
            notes = str(enrichment.get("notes") or "").strip()
            existing_notes = str(listing_doc.get("attribute_notes") or "").strip()
            next_notes = existing_notes
            if notes:
                next_notes = (
                    f"{existing_notes}\nSeller reply: {notes}"
                    if existing_notes
                    else f"Seller reply: {notes}"
                )

            await listings.update_one(
                {"_id": listing_doc["_id"]},
                {
                    "$set": {
                        "extracted_attributes": merged_attributes,
                        "missing_fields": remaining_missing_fields,
                        "seller_questions": remaining_questions,
                        "attribute_notes": next_notes,
                    }
                },
            )

        await bargain_items.update_one(
            {"shopping_list_id": shopping_list_id, "listing_id": listing_id},
            {
                "$set": {
                    "status": "ready_to_negotiate",
                    "last_seller_message": seller_reply,
                    "updated_at": _now(),
                },
                "$push": {
                    "conversation": {"role": "seller", "content": seller_reply}
                },
            },
        )
        updated.append(
            {
                "listing_id": listing_id,
                "thread_url": thread_url,
                "message": seller_reply,
                "enrichment": enrichment,
                "status": "ready_to_negotiate",
            }
        )

    return {
        "shopping_list_id": shopping_list_id,
        "checked_count": len(checked),
        "updated_count": len(updated),
        "skipped_count": len(skipped),
        "checked": checked,
        "updated": updated,
        "skipped": skipped,
    }
