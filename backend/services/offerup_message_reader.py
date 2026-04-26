"""Read OfferUp chat messages without triggering negotiation.

This is the reusable "check for new seller messages" layer. It opens the
OfferUp chat for a listing using the shared logged-in Chrome profile, scrapes
recent visible chat text, and returns the newest seller-looking message that is
not already present in the supplied conversation history.
"""

from __future__ import annotations

import asyncio
import os
import queue
import re
import sys
import threading
from contextlib import suppress
from collections.abc import Awaitable, Callable
from typing import Any

from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

from backend.services._browser_offerup import launch_logged_in_chrome

_OFFERUP_READER_LOCK = asyncio.Lock()
OFFERUP_INBOX_URL = "https://offerup.com/inbox"
_CHAT_EXTRACTOR_TOOL_NAME = "return_offerup_chat"
_CHAT_EXTRACTOR_TOOL: dict[str, Any] = {
    "name": _CHAT_EXTRACTOR_TOOL_NAME,
    "description": "Return only actual OfferUp chat messages visible in the page snapshot.",
    "input_schema": {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {
                            "type": "string",
                            "enum": ["buyer", "seller", "unknown"],
                            "description": "buyer is the signed-in user; seller is the other person.",
                        },
                        "text": {
                            "type": "string",
                            "description": "The message body only, without timestamp/delivery status.",
                        },
                    },
                    "required": ["role", "text"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["messages"],
        "additionalProperties": False,
    },
}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").split()).strip().lower()


def _strip_message_metadata(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    text = re.sub(r"^\d{1,2}:\d{2}\s*(?:AM|PM)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*(?:Delivered|Read|Sent)\s*$", "", text, flags=re.I)
    return text.strip()


def _looks_like_chat_chrome(value: str) -> bool:
    normalized = _normalize_text(value)
    if not normalized:
        return True
    ignored_exact = {
        "ask",
        "back to main",
        "cancel",
        "delivered",
        "enter your offer",
        "make offer",
        "message",
        "new message",
        "send",
        "send a message",
    }
    ignored_contains = (
        "click a message to send",
        "chat securely on the app",
        "offer up reviews",
        "posted ",
        "skip advertisement",
        "skip to main content",
        "sold by",
    )
    return normalized in ignored_exact or any(
        fragment in normalized for fragment in ignored_contains
    )


def _is_known_message(value: str, known_messages: set[str]) -> bool:
    normalized = _normalize_text(_strip_message_metadata(value))
    if not normalized:
        return True
    for known in known_messages:
        if not known:
            continue
        if normalized == known:
            return True
        if len(known) >= 12 and known in normalized:
            return True
        if len(normalized) >= 12 and normalized in known:
            return True
    return False


def _run_browser_task(factory: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
    """Run Playwright in a loop that supports subprocesses on Windows."""
    out: queue.Queue[tuple[str, dict[str, Any] | BaseException]] = queue.Queue()

    def target() -> None:
        try:
            if sys.platform == "win32":
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            out.put(("result", asyncio.run(factory())))
        except BaseException as exc:
            out.put(("error", exc))

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join()
    kind, value = out.get()
    if kind == "error":
        raise value
    return value  # type: ignore[return-value]


async def _click_first_visible(loc) -> bool:
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


async def _open_offerup_chat(page: Page, listing_url: str) -> None:
    """Navigate to an OfferUp listing and open the chat panel/composer."""
    await page.goto(listing_url, wait_until="domcontentloaded", timeout=60_000)
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=15_000)
    await asyncio.sleep(1.5)

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

    for name in (
        "Ask",
        "Message",
        "Message seller",
        "Send message",
        "Contact seller",
        "Make offer",
        "Chat",
    ):
        if await _click_first_visible(page.get_by_role("button", name=name, exact=False)):
            return
        if await _click_first_visible(page.get_by_role("link", name=name, exact=False)):
            return

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
        if await _click_first_visible(page.locator(sel)):
            return

    clicked = await page.evaluate(
        """
        () => {
          const wanted = ["ask", "message", "message seller", "send message", "contact seller", "make offer", "chat"];
          const nodes = Array.from(document.querySelectorAll("button, a, [role='button']"));
          for (const node of nodes) {
            const text = ((node.innerText || node.textContent || "").trim()).toLowerCase();
            if (!text || !wanted.some((w) => text.includes(w))) continue;
            node.scrollIntoView({ block: "center", behavior: "instant" });
            node.click();
            return true;
          }
          return false;
        }
        """
    )
    if clicked:
        await asyncio.sleep(1.2)
        return

    body_text = ""
    with suppress(Exception):
        body_text = (await page.locator("body").inner_text())[:5000].lower()
    if "log in" in body_text or "sign in" in body_text:
        raise RuntimeError(
            f"Messaging unavailable on {listing_url} - OfferUp appears to require login."
        )
    raise RuntimeError(f"Message button not found on {listing_url}.")


async def _extract_chat_candidates(page: Page) -> list[dict[str, str]]:
    """Extract visible OfferUp chat messages from a scoped page snapshot via LLM."""
    snapshot = await _chat_snapshot(page)
    if not snapshot["text"] and not snapshot["html"]:
        return []
    return _extract_chat_candidates_with_llm(snapshot)


async def _chat_snapshot(page: Page) -> dict[str, str]:
    """Return full page HTML/text after OfferUp has opened a thread page."""
    return await page.evaluate(
        """
        () => {
          return {
            url: window.location.href,
            title: document.title || "",
            text: (document.body.innerText || "").replace(/\\s+/g, " ").trim().slice(-12000),
            html: (document.body.outerHTML || "").replace(/\\s+/g, " ").trim().slice(-24000),
          };
        }
        """,
    )


def _extract_chat_candidates_with_llm(snapshot: dict[str, str]) -> list[dict[str, str]]:
    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    user_message = (
        "Extract the actual OfferUp chat transcript from this browser snapshot.\n"
        "Rules:\n"
        "- Return only real messages sent between buyer and seller.\n"
        "- Ignore page chrome, seller profile text, listing details, suggested quick replies, "
        "buttons, timestamps, and delivery/read receipts.\n"
        "- If a message is from the signed-in user / me / buyer, role must be buyer.\n"
        "- If a message is from the other person / seller, role must be seller.\n"
        "- If the role is truly not inferable, use unknown, but still only for real chat messages.\n"
        "- Do not invent messages.\n\n"
        f"URL: {snapshot.get('url', '')}\n"
        f"Page title: {snapshot.get('title', '')}\n\n"
        f"Visible text:\n{snapshot.get('text', '')}\n\n"
        f"Scoped HTML:\n{snapshot.get('html', '')}"
    )

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        tools=[_CHAT_EXTRACTOR_TOOL],
        tool_choice={"type": "tool", "name": _CHAT_EXTRACTOR_TOOL_NAME},
        messages=[{"role": "user", "content": user_message}],
    )

    payload: dict[str, Any] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == _CHAT_EXTRACTOR_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            break
    if payload is None:
        raise RuntimeError("Claude did not return structured chat messages.")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        return []

    candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in raw_messages:
        if not isinstance(row, dict):
            continue
        text = _strip_message_metadata(str(row.get("text") or "").strip())
        role = str(row.get("role") or "unknown").strip().lower()
        if role not in {"buyer", "seller", "unknown"}:
            role = "unknown"
        key = (role, _normalize_text(text))
        if key in seen:
            continue
        seen.add(key)
        if text and not _looks_like_chat_chrome(text):
            candidates.append({"text": text, "role": role})
    return candidates


async def _open_offerup_inbox(page: Page) -> None:
    await page.goto(OFFERUP_INBOX_URL, wait_until="domcontentloaded", timeout=60_000)
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=15_000)
    await asyncio.sleep(2)

    body_text = ""
    with suppress(Exception):
        body_text = (await page.locator("body").inner_text())[:5000].lower()
    if "log in" in body_text or "sign in" in body_text:
        raise RuntimeError("OfferUp inbox appears to require login.")


async def _extract_unread_threads(page: Page, *, limit: int) -> list[dict[str, str]]:
    raw = await page.evaluate(
        """
        (limit) => {
          const rows = [];
          const seen = new Set();
          const unreadHints = ["unread", "new message", "new", "notification"];
          const anchors = Array.from(document.querySelectorAll("a[href]"));

          for (const anchor of anchors) {
            const href = anchor.href || "";
            const text = (anchor.innerText || anchor.textContent || "").replace(/\\s+/g, " ").trim();
            if (!href || !text || seen.has(href)) continue;

            const lowerHref = href.toLowerCase();
            const lowerText = text.toLowerCase();
            const looksLikeThread =
              lowerHref.includes("inbox") ||
              lowerHref.includes("message") ||
              lowerHref.includes("chat");
            if (!looksLikeThread) continue;

            const aria = (
              anchor.getAttribute("aria-label") ||
              anchor.closest("[aria-label]")?.getAttribute("aria-label") ||
              ""
            ).toLowerCase();
            const className = (
              anchor.className ||
              anchor.closest("[class]")?.className ||
              ""
            ).toString().toLowerCase();
            const isUnread =
              unreadHints.some((hint) => lowerText.includes(hint)) ||
              unreadHints.some((hint) => aria.includes(hint)) ||
              unreadHints.some((hint) => className.includes(hint)) ||
              !!anchor.querySelector('[aria-label*="unread" i], [class*="unread" i], [data-testid*="unread" i]');

            if (!isUnread) continue;
            seen.add(href);
            rows.push({
              thread_url: href,
              preview: text.slice(0, 500),
            });
            if (rows.length >= limit) break;
          }

          return rows;
        }
        """,
        limit,
    )
    if not isinstance(raw, list):
        return []

    threads: list[dict[str, str]] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        thread_url = str(row.get("thread_url") or "").strip()
        preview = str(row.get("preview") or "").strip()
        if thread_url:
            threads.append({"thread_url": thread_url, "preview": preview})
    return threads


async def _read_thread_messages(
    page: Page,
    thread_url: str,
    *,
    known_messages: list[str],
) -> dict[str, Any]:
    await page.goto(thread_url, wait_until="domcontentloaded", timeout=60_000)
    with suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=10_000)
    await asyncio.sleep(1.5)

    candidates = await _extract_chat_candidates(page)
    known = {_normalize_text(message) for message in known_messages if message}
    latest_row = candidates[-1] if candidates else None
    latest = None
    unread_messages: list[dict[str, str]] = []
    if (
        latest_row
        and latest_row.get("role") == "seller"
        and not _is_known_message(latest_row.get("text", ""), known)
    ):
        latest = latest_row["text"]
        unread_messages = [latest_row]
    return {
        "thread_url": thread_url,
        "has_new_message": latest is not None,
        "latest_message": latest,
        "messages": unread_messages,
        "candidates": candidates,
    }


def pick_new_seller_message(
    candidates: list[dict[str, str]],
    conversation: list[dict[str, str]],
    *,
    listing_title: str = "",
) -> str | None:
    """Return the latest seller message only when the seller spoke last."""
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

    cleaned: list[dict[str, str]] = []
    for row in candidates:
        text = _strip_message_metadata(row.get("text", ""))
        role = row.get("role", "unknown")
        normalized = _normalize_text(text)
        if (
            not normalized
            or normalized in ignore_exact
            or _looks_like_chat_chrome(text)
        ):
            continue
        if role == "unknown" and "$" not in text and len(text.split()) < 3:
            continue
        cleaned.append({"text": text, "role": role})

    if not cleaned:
        return None

    latest = cleaned[-1]
    if latest["role"] != "seller":
        return None
    if _is_known_message(latest["text"], known):
        return None
    return latest["text"]


async def check_offerup_messages(
    listing_url: str,
    *,
    conversation: list[dict[str, str]] | None = None,
    listing_title: str = "",
) -> dict[str, Any]:
    """Open a listing chat and return the newest unseen seller message."""
    async with _OFFERUP_READER_LOCK:
        return await asyncio.to_thread(
            _run_browser_task,
            lambda: _check_offerup_messages_in_browser(
                listing_url,
                conversation=list(conversation or []),
                listing_title=listing_title,
            ),
        )


async def check_offerup_thread_messages(
    thread_url: str,
    *,
    known_messages: list[str] | None = None,
) -> dict[str, Any]:
    """Read an already-known OfferUp thread URL without opening a listing page."""
    async with _OFFERUP_READER_LOCK:
        return await asyncio.to_thread(
            _run_browser_task,
            lambda: _check_offerup_thread_messages_in_browser(
                thread_url,
                known_messages=list(known_messages or []),
            ),
        )


async def _check_offerup_messages_in_browser(
    listing_url: str,
    *,
    conversation: list[dict[str, str]],
    listing_title: str = "",
) -> dict[str, Any]:
    """Browser-loop implementation for a single listing chat check."""
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await _open_offerup_chat(page, listing_url)
            candidates = await _extract_chat_candidates(page)
            message = pick_new_seller_message(
                candidates,
                conversation,
                listing_title=listing_title,
            )
            return {
                "listing_url": listing_url,
                "has_new_message": message is not None,
                "message": message,
                "candidates": candidates,
            }
        finally:
            await context.close()


async def _check_offerup_thread_messages_in_browser(
    thread_url: str,
    *,
    known_messages: list[str],
) -> dict[str, Any]:
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            return await _read_thread_messages(
                page,
                thread_url,
                known_messages=known_messages,
            )
        finally:
            await context.close()


async def _check_unread_offerup_chats_in_browser(
    *,
    limit: int = 10,
    known_messages_by_thread: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Browser-loop implementation for inbox unread checks."""
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await _open_offerup_inbox(page)
            threads = await _extract_unread_threads(page, limit=limit)

            results: list[dict[str, Any]] = []
            known_by_thread = known_messages_by_thread or {}
            for thread in threads:
                thread_url = thread["thread_url"]
                thread_result = await _read_thread_messages(
                    page,
                    thread_url,
                    known_messages=known_by_thread.get(thread_url, []),
                )
                thread_result["preview"] = thread.get("preview")
                results.append(thread_result)

            unread_count = sum(1 for row in results if row.get("has_new_message"))
            return {
                "unread_count": unread_count,
                "threads": results,
            }
        finally:
            await context.close()


async def _legacy_check_offerup_messages(
    listing_url: str,
    *,
    conversation: list[dict[str, str]] | None = None,
    listing_title: str = "",
) -> dict[str, Any]:
    """Deprecated direct-loop implementation kept for reference during refactor."""
    async with _OFFERUP_READER_LOCK:
        async with async_playwright() as p:
            context = await launch_logged_in_chrome(p)
            try:
                page = context.pages[0] if context.pages else await context.new_page()
                await _open_offerup_chat(page, listing_url)
                candidates = await _extract_chat_candidates(page)
                message = pick_new_seller_message(
                    candidates,
                    list(conversation or []),
                    listing_title=listing_title,
                )
                return {
                    "listing_url": listing_url,
                    "has_new_message": message is not None,
                    "message": message,
                    "candidates": candidates,
                }
            finally:
                await context.close()


async def check_unread_offerup_chats(
    *,
    limit: int = 10,
    known_messages_by_thread: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Open the OfferUp inbox and read unread-looking browser threads."""
    async with _OFFERUP_READER_LOCK:
        return await asyncio.to_thread(
            _run_browser_task,
            lambda: _check_unread_offerup_chats_in_browser(
                limit=limit,
                known_messages_by_thread=known_messages_by_thread,
            ),
        )
