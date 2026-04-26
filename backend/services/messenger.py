"""Send a message to a Facebook Marketplace seller.

Uses Browserbase (with the persistent FB_CONTEXT_ID for login) + Playwright over
CDP to directly drive the message composer. Stagehand was tried first but its
natural-language `act()` couldn't reliably overwrite FB's pre-filled default
message — Playwright locators give us deterministic clear-and-fill behavior.

Usage:
    python -m backend.services.messenger \\
        "https://www.facebook.com/marketplace/item/123456" \\
        "Hi, is this still available?"
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from browserbase import AsyncBrowserbase
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

load_dotenv()

DEBUG_DIR = Path("scraper/output/debug")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


async def _open_composer(page: Page) -> bool:
    """Try to make the message composer visible/focused.

    Some listings have an inline 'Send seller a message' composer; others hide
    it behind a 'Message' button. Try clicking the button if we see one — it's
    a no-op when the composer is already inline.
    """
    try:
        msg_button = page.get_by_role("button", name="Message").first
        if await msg_button.is_visible(timeout=2000):
            await msg_button.click()
            await asyncio.sleep(1)
    except Exception:
        pass
    return True


async def _snap(page: Page, label: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=False)
        print(f"[messenger] snap → {DEBUG_DIR / f'{label}.png'}")
    except Exception as e:
        print(f"[messenger] snap '{label}' failed: {e}")


async def _dump_textboxes(page: Page) -> None:
    """Log all visible textboxes and contenteditables on the page."""
    print("[messenger] --- visible textboxes ---")
    try:
        boxes = page.locator('[role="textbox"], [contenteditable="true"]')
        count = await boxes.count()
        for i in range(count):
            el = boxes.nth(i)
            try:
                if not await el.is_visible():
                    continue
                aria = await el.get_attribute("aria-label")
                placeholder = await el.get_attribute("placeholder")
                role = await el.get_attribute("role")
                ce = await el.get_attribute("contenteditable")
                text = (await el.inner_text())[:60]
                print(
                    f"  [{i}] role={role!r} ce={ce!r} aria={aria!r} "
                    f"placeholder={placeholder!r} text={text!r}"
                )
            except Exception as e:
                print(f"  [{i}] err: {e}")
    except Exception as e:
        print(f"[messenger] dump err: {e}")
    print("[messenger] -------------------------")


async def _fill_and_send(page: Page, message_text: str) -> None:
    """Locate the composer textbox, replace its contents, click Send."""
    await _dump_textboxes(page)

    # FB Marketplace's inline composer has an aria-label that mentions the seller's
    # name plus "Message". Match anything with role=textbox + aria-label containing
    # "message". If that fails, fall back to any visible contenteditable.
    composer = page.get_by_role("textbox", name=re.compile(r"message", re.I)).first
    try:
        await composer.wait_for(state="visible", timeout=10000)
    except Exception:
        print("[messenger] role=textbox name=message not found — trying contenteditable")
        # Pick the FIRST visible contenteditable that's NOT the search bar
        composer = page.locator(
            '[contenteditable="true"]:not([aria-label*="Search" i])'
        ).first
        await composer.wait_for(state="visible", timeout=10000)

    aria = await composer.get_attribute("aria-label")
    print(f"[messenger] using composer aria-label={aria!r}")

    await composer.scroll_into_view_if_needed()
    await composer.click()
    await asyncio.sleep(0.5)
    await _snap(page, "01_composer_focused")

    initial = await composer.inner_text()
    print(f"[messenger] composer initial: {initial!r}")

    # fill() works for contenteditable in modern Playwright and bypasses keyboard quirks
    try:
        await composer.fill(message_text)
        print("[messenger] used fill()")
    except Exception as e:
        print(f"[messenger] fill() failed ({e}); falling back to keyboard")
        await composer.click()
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Delete")
        await composer.press_sequentially(message_text, delay=30)

    await asyncio.sleep(0.5)
    await _snap(page, "03_after_type")
    after = await composer.inner_text()
    print(f"[messenger] composer after type: {after!r}")

    # Try a few names — FB sometimes labels Send button as "Send" or "Send message"
    send_btn = page.get_by_role("button", name=re.compile(r"^send( message)?$", re.I)).first
    try:
        await send_btn.wait_for(state="visible", timeout=8000)
    except Exception:
        print("[messenger] no Send button found — pressing Enter as fallback")
        await composer.press("Enter")
        await asyncio.sleep(2)
        await _snap(page, "04_after_send")
        return

    print("[messenger] clicking Send")
    await send_btn.click()
    await asyncio.sleep(2)
    await _snap(page, "04_after_send")


async def message_seller(listing_url: str, message_text: str) -> dict:
    """Open the listing in a logged-in FB session and send a message.

    Returns {"success": bool, "error": str | None}.
    """
    bb_api_key = _require_env("BROWSERBASE_API_KEY")
    bb_project_id = _require_env("BROWSERBASE_PROJECT_ID")
    fb_context_id = _require_env("FB_CONTEXT_ID")

    async with AsyncBrowserbase(api_key=bb_api_key) as bb:
        session = await bb.sessions.create(
            project_id=bb_project_id,
            browser_settings={"context": {"id": fb_context_id, "persist": False}},
        )
        session_id = session.id

        try:
            urls = await bb.sessions.debug(session_id)
            ws_url = urls.ws_url

            async with async_playwright() as p:
                browser = await p.chromium.connect_over_cdp(ws_url)
                try:
                    context = browser.contexts[0]
                    page = context.pages[0] if context.pages else await context.new_page()

                    await page.goto(listing_url, wait_until="commit", timeout=60000)
                    await asyncio.sleep(7)
                    await _snap(page, "00_after_load")

                    await _open_composer(page)
                    await _fill_and_send(page, message_text)
                    await asyncio.sleep(3)

                    return {"success": True, "error": None}
                finally:
                    await browser.close()
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            try:
                await bb.sessions.update(session_id, project_id=bb_project_id, status="REQUEST_RELEASE")
            except Exception:
                pass


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Message a FB Marketplace seller.")
    parser.add_argument("listing_url", help="Facebook Marketplace item URL")
    parser.add_argument("message", help="Message body to send")
    args = parser.parse_args()

    print(f"[messenger] {args.listing_url}")
    result = await message_seller(args.listing_url, args.message)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
