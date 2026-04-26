"""Send a message to a Facebook Marketplace seller.

Uses a LOCAL Playwright browser with a persistent Chrome profile
(scraper/.chrome-profile) — the same profile populated by `node scripts/fb_login.js`.
Running locally means the browser uses your own IP, which matches your
phone-verified location and avoids the "Verify your location" block.

Usage:
    python -m backend.services.messenger \
        "https://www.facebook.com/marketplace/item/123456" \
        "Hi, is this still available?"
"""

import argparse
import asyncio
import json
import random
import re
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright

from backend.services._browser import attach_to_user_chrome, launch_logged_in_chrome

load_dotenv()

DEBUG_DIR = Path("scraper/output/debug")


async def _warm_up_session(page: Page) -> None:
    """Browse FB normally for ~15s before going to the listing.

    FB's risk model treats sessions that land cold on a listing and
    immediately try to message as bot-like. Warming up with home-feed +
    marketplace browse + scroll mirrors what a real user does.
    """
    print("[messenger] warming up session...")
    try:
        await page.goto("https://www.facebook.com/", wait_until="commit", timeout=30000)
        await asyncio.sleep(random.uniform(3, 5))
        for _ in range(2):
            await page.mouse.wheel(0, random.randint(400, 1200))
            await asyncio.sleep(random.uniform(1, 2))
    except Exception as e:
        print(f"[messenger] warmup home failed: {e}")

    try:
        await page.goto(
            "https://www.facebook.com/marketplace/", wait_until="commit", timeout=30000
        )
        await asyncio.sleep(random.uniform(3, 5))
        for _ in range(2):
            await page.mouse.wheel(0, random.randint(400, 1000))
            await asyncio.sleep(random.uniform(1, 2))
    except Exception as e:
        print(f"[messenger] warmup marketplace failed: {e}")
    print("[messenger] warmup done")


async def _hit_location_gate(page: Page) -> bool:
    """True if FB's 'Verify your location' modal is blocking the composer."""
    for sel in (
        'text="Verify your location"',
        'text="check your location"',
        'text="open the mobile app"',
    ):
        try:
            if await page.locator(sel).first.is_visible(timeout=1500):
                return True
        except Exception:
            continue
    return False


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


async def _resolve_composer(page: Page):
    """Find the seller-message composer, anchored on visible scaffolding text.

    FB ships several contenteditables on the page (search bar, comment boxes,
    etc.); a generic role=textbox match has hit empty wrappers in the past.
    Strategy: anchor on the "Send seller a message" / "Message [seller]" text
    that always sits above the composer, then take the contenteditable inside
    that section. Fall back to the LAST visible contenteditable on the page,
    since the composer is rendered late in the DOM.
    """
    # Anchor: the section on a marketplace item that holds the inline composer
    candidates = [
        page.locator(
            'div:has(:text("Send seller a message")) [contenteditable="true"]'
        ).first,
        page.locator(
            'div:has(:text-matches("Message ", "i")) [contenteditable="true"]'
        ).first,
        page.get_by_role("textbox", name=re.compile(r"message", re.I)).first,
    ]
    for cand in candidates:
        try:
            await cand.wait_for(state="visible", timeout=4000)
            return cand
        except Exception:
            continue

    # Last-resort: pick the LAST visible contenteditable that isn't search
    print("[messenger] anchored locators failed — using last contenteditable")
    boxes = page.locator(
        '[contenteditable="true"]:not([aria-label*="Search" i])'
    )
    count = await boxes.count()
    for i in range(count - 1, -1, -1):
        cand = boxes.nth(i)
        try:
            if await cand.is_visible():
                return cand
        except Exception:
            continue
    raise RuntimeError("no composer textbox found on page")


async def _fill_and_send(page: Page, message_text: str) -> None:
    """Locate the composer textbox, replace its contents, click Send."""
    await _dump_textboxes(page)

    composer = await _resolve_composer(page)

    aria = await composer.get_attribute("aria-label")
    print(f"[messenger] using composer aria-label={aria!r}")

    await composer.scroll_into_view_if_needed()
    await composer.click()
    await asyncio.sleep(0.5)
    await _snap(page, "01_composer_focused")

    initial = await composer.inner_text()
    print(f"[messenger] composer initial: {initial!r}")

    # Try fill() first; if it silently no-ops (contenteditable wrappers around
    # Lexical/Draft.js editors do this) fall through to keyboard.
    try:
        await composer.fill(message_text)
        print("[messenger] used fill()")
    except Exception as e:
        print(f"[messenger] fill() raised ({e}); falling back to keyboard")

    await asyncio.sleep(0.3)
    intermediate = await composer.inner_text()
    if message_text.strip() not in intermediate:
        print(f"[messenger] composer empty after fill (got {intermediate!r}); using keyboard")
        await composer.click()
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Delete")
        await page.keyboard.type(message_text, delay=30)

    await asyncio.sleep(0.5)
    await _snap(page, "03_after_type")
    after = await composer.inner_text()
    print(f"[messenger] composer after type: {after!r}")

    # FB labels the Send action inconsistently across A/B variants — sometimes
    # role=button with name="Send", sometimes a div[role=button] with no text
    # and just an svg icon, sometimes inside a labeled wrapper. Dump nearby
    # buttons for visibility, then try strategies in order.
    await _dump_send_candidates(page, composer)

    if await _try_send(page, composer):
        await asyncio.sleep(2)
        await _snap(page, "04_after_send")
        return

    print("[messenger] all Send strategies failed")
    await _snap(page, "04_after_send")


async def _dump_send_candidates(page: Page, composer) -> None:
    """Log every clickable in the composer's parent section."""
    print("[messenger] --- send candidates ---")
    try:
        parent = composer.locator(
            "xpath=ancestor::div[contains(@class,'') and .//button][1]"
        ).first
        await parent.wait_for(state="visible", timeout=2000)
        clickables = parent.locator('button, [role="button"]')
        n = await clickables.count()
        for i in range(n):
            el = clickables.nth(i)
            try:
                if not await el.is_visible():
                    continue
                aria = await el.get_attribute("aria-label")
                text = (await el.inner_text())[:40]
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                print(f"  [{i}] <{tag}> aria={aria!r} text={text!r}")
            except Exception as e:
                print(f"  [{i}] err: {e}")
    except Exception as e:
        print(f"[messenger] dump send err: {e}")
    print("[messenger] -----------------------")


async def _try_send(page: Page, composer) -> bool:
    """Try multiple send strategies; return True on first success."""
    # Strategy 1: role=button with name "Send"
    try:
        btn = page.get_by_role("button", name=re.compile(r"^send( message)?$", re.I)).first
        if await btn.is_visible(timeout=3000):
            print("[messenger] send: role=button name=Send")
            await btn.click()
            return True
    except Exception as e:
        print(f"[messenger] strategy 1 failed: {e}")

    # Strategy 2: aria-label="Send" on any element (catches div[role=button])
    try:
        btn = page.locator('[aria-label="Send"]').first
        if await btn.is_visible(timeout=2000):
            print("[messenger] send: [aria-label=Send]")
            await btn.click()
            return True
    except Exception as e:
        print(f"[messenger] strategy 2 failed: {e}")

    # Strategy 3: a [role=button] sibling/descendant of the composer's parent
    try:
        scope = composer.locator(
            'xpath=ancestor::div[.//*[@role="button" or self::button]][1]'
        ).first
        btn = scope.locator(
            '[role="button"], button'
        ).filter(has_not=composer).last
        if await btn.is_visible(timeout=2000):
            aria = await btn.get_attribute("aria-label")
            print(f"[messenger] send: nearby button aria={aria!r}")
            await btn.click()
            return True
    except Exception as e:
        print(f"[messenger] strategy 3 failed: {e}")

    # Strategy 4: keyboard Enter inside composer
    try:
        print("[messenger] send: Enter")
        await composer.press("Enter")
        return True
    except Exception as e:
        print(f"[messenger] strategy 4 failed: {e}")

    return False


async def message_seller(
    listing_url: str,
    message_text: str,
    *,
    cdp: bool = False,
    cdp_url: str = "http://localhost:9222",
    warmup: bool = True,
) -> dict:
    """Open the listing in a local logged-in browser and send a message.

    Args:
        cdp: if True, attach to a Chrome already started with
            --remote-debugging-port=9222 instead of launching one. Use this
            when FB still gates the Playwright-launched browser despite the
            stealth patches in _browser.py.
        warmup: if True, browse facebook.com + /marketplace/ briefly before
            going to the listing — softens FB's bot-detection heuristics.

    Returns {"success": bool, "error": str | None}.
    """
    async with async_playwright() as p:
        close_context = True
        try:
            if cdp:
                context = await attach_to_user_chrome(p, cdp_url)
                # Don't tear down the user's real browser when we're done.
                close_context = False
            else:
                context = await launch_logged_in_chrome(p)
        except Exception as e:
            return {"success": False, "error": f"Browser launch failed: {e}"}

        try:
            page = context.pages[0] if context.pages else await context.new_page()

            if warmup:
                await _warm_up_session(page)

            await page.goto(listing_url, wait_until="commit", timeout=60000)
            await asyncio.sleep(7)
            await _snap(page, "00_after_load")

            await _open_composer(page)

            if await _hit_location_gate(page):
                await _snap(page, "00_location_gate")
                return {
                    "success": False,
                    "error": (
                        "FB_LOCATION_GATE: desktop session still gated. Try --cdp "
                        "with a manually-started Chrome (see plan)."
                    ),
                }

            await _fill_and_send(page, message_text)
            await asyncio.sleep(3)

            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            if close_context:
                await context.close()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Message a FB Marketplace seller.")
    parser.add_argument("listing_url", help="Facebook Marketplace item URL")
    parser.add_argument("message", help="Message body to send")
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="Attach to a Chrome started with --remote-debugging-port=9222 "
        "instead of launching one (Layer 3 bypass)",
    )
    parser.add_argument(
        "--cdp-url",
        default="http://localhost:9222",
        help="CDP endpoint for --cdp mode (default: http://localhost:9222)",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip the warm-up browse before the listing nav (faster, more bot-like)",
    )
    args = parser.parse_args()

    print(f"[messenger] {args.listing_url}")
    result = await message_seller(
        args.listing_url,
        args.message,
        cdp=args.cdp,
        cdp_url=args.cdp_url,
        warmup=not args.no_warmup,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
