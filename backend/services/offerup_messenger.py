"""Send a message to an OfferUp seller.

Uses a LOCAL Playwright browser with a persistent Chrome profile
(scraper/.chrome-profile-offerup) — the same profile populated by
`python scripts/offerup_login.py`.

Unlike FB Marketplace, OfferUp does NOT have a "Verify your location" gate
on messaging. The compose flow is simpler: navigate to listing → click
"Ask" or "Make offer" → type message → send.

Usage:
    python -m backend.services.offerup_messenger \
        "https://offerup.com/item/detail/123456" \
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

from backend.services._browser_offerup import attach_to_user_chrome, launch_logged_in_chrome

load_dotenv()

DEBUG_DIR = Path("scraper/output/debug")


async def _warm_up_session(page: Page) -> None:
    """Browse OfferUp briefly before navigating to the listing.

    Lighter warmup than FB — OfferUp's bot detection is less aggressive,
    but we still want to avoid cold-landing on a listing detail page.
    """
    print("[offerup-msg] warming up session...")
    try:
        await page.goto("https://offerup.com/", wait_until="commit", timeout=30000)
        await asyncio.sleep(random.uniform(2, 4))
        for _ in range(2):
            await page.mouse.wheel(0, random.randint(300, 800))
            await asyncio.sleep(random.uniform(0.5, 1.5))
    except Exception as e:
        print(f"[offerup-msg] warmup failed: {e}")
    print("[offerup-msg] warmup done")


async def _snap(page: Page, label: str) -> None:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(DEBUG_DIR / f"{label}.png"), full_page=False)
        print(f"[offerup-msg] snap → {DEBUG_DIR / f'{label}.png'}")
    except Exception as e:
        print(f"[offerup-msg] snap '{label}' failed: {e}")


async def _dump_textboxes(page: Page) -> None:
    """Log all visible textboxes and contenteditables on the page."""
    print("[offerup-msg] --- visible textboxes ---")
    try:
        boxes = page.locator(
            '[role="textbox"], [contenteditable="true"], textarea, input[type="text"]'
        )
        count = await boxes.count()
        for i in range(count):
            el = boxes.nth(i)
            try:
                if not await el.is_visible():
                    continue
                aria = await el.get_attribute("aria-label")
                placeholder = await el.get_attribute("placeholder")
                role = await el.get_attribute("role")
                tag = await el.evaluate("e => e.tagName.toLowerCase()")
                text = ""
                if tag == "textarea" or tag == "input":
                    text = (await el.input_value())[:60]
                else:
                    text = (await el.inner_text())[:60]
                print(
                    f"  [{i}] <{tag}> role={role!r} aria={aria!r} "
                    f"placeholder={placeholder!r} text={text!r}"
                )
            except Exception as e:
                print(f"  [{i}] err: {e}")
    except Exception as e:
        print(f"[offerup-msg] dump err: {e}")
    print("[offerup-msg] -------------------------")


async def _open_composer(page: Page) -> bool:
    """Try to make the message composer visible/focused.

    OfferUp listing detail pages typically have:
    - An "Ask" button for asking the seller a question
    - A "Make offer" button for price negotiation
    - Sometimes an inline message input

    We try clicking "Ask" first since it opens a generic message composer.
    """
    # Try various button labels OfferUp uses
    for label in (
        "Ask",
        "Message",
        "Message seller",
        "Send message",
        "Contact seller",
        "Make offer",
    ):
        try:
            btn = page.get_by_role("button", name=re.compile(rf"^{label}$", re.I)).first
            if await btn.is_visible(timeout=2000):
                print(f"[offerup-msg] clicking '{label}' button")
                await btn.click()
                await asyncio.sleep(1.5)
                return True
        except Exception:
            continue

    # Fallback: look for any button with messaging-related text
    try:
        btn = page.locator(
            'button:has-text("Ask"), '
            'button:has-text("Message"), '
            'a:has-text("Message"), '
            '[data-testid*="message" i], '
            '[data-testid*="ask" i]'
        ).first
        if await btn.is_visible(timeout=2000):
            print("[offerup-msg] clicking fallback message button")
            await btn.click()
            await asyncio.sleep(1.5)
            return True
    except Exception:
        pass

    print("[offerup-msg] no message button found — composer may be inline")
    return True


async def _resolve_composer(page: Page):
    """Find the message composer input field.

    OfferUp's message input is typically a <textarea> or standard <input>,
    much simpler than FB's contenteditable Lexical editor.
    """
    candidates = [
        # Textarea with message-related attributes
        page.locator(
            'textarea[placeholder*="message" i], '
            'textarea[placeholder*="type" i], '
            'textarea[aria-label*="message" i]'
        ).first,
        # Input fields
        page.locator(
            'input[placeholder*="message" i], '
            'input[placeholder*="type" i], '
            'input[aria-label*="message" i]'
        ).first,
        # Contenteditable (less common on OfferUp)
        page.locator(
            '[contenteditable="true"][aria-label*="message" i]'
        ).first,
        # Generic textbox role
        page.get_by_role("textbox", name=re.compile(r"message", re.I)).first,
        # Any visible textarea
        page.locator("textarea").first,
        # Any visible textbox role
        page.get_by_role("textbox").first,
    ]

    for cand in candidates:
        try:
            await cand.wait_for(state="visible", timeout=4000)
            return cand
        except Exception:
            continue

    # Last-resort: pick the last visible text input on the page
    print("[offerup-msg] standard locators failed — using last visible input")
    inputs = page.locator('textarea, input[type="text"], [contenteditable="true"]')
    count = await inputs.count()
    for i in range(count - 1, -1, -1):
        cand = inputs.nth(i)
        try:
            if await cand.is_visible():
                return cand
        except Exception:
            continue

    raise RuntimeError("no message input found on page")


async def _fill_and_send(page: Page, message_text: str) -> None:
    """Locate the composer, type the message, and click Send."""
    await _dump_textboxes(page)

    composer = await _resolve_composer(page)

    tag = await composer.evaluate("e => e.tagName.toLowerCase()")
    aria = await composer.get_attribute("aria-label")
    placeholder = await composer.get_attribute("placeholder")
    print(f"[offerup-msg] using composer <{tag}> aria={aria!r} placeholder={placeholder!r}")

    await composer.scroll_into_view_if_needed()
    await composer.click()
    await asyncio.sleep(0.5)
    await _snap(page, "offerup_01_composer_focused")

    # Fill the message — textarea/input supports fill() reliably
    try:
        await composer.fill(message_text)
        print("[offerup-msg] used fill()")
    except Exception as e:
        print(f"[offerup-msg] fill() raised ({e}); falling back to keyboard")
        await composer.click()
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Delete")
        await page.keyboard.type(message_text, delay=30)

    await asyncio.sleep(0.5)
    await _snap(page, "offerup_02_after_type")

    if await _try_send(page, composer):
        await asyncio.sleep(2)
        await _snap(page, "offerup_03_after_send")
        return

    print("[offerup-msg] all Send strategies failed")
    await _snap(page, "offerup_03_after_send")


async def _try_send(page: Page, composer) -> bool:
    """Try multiple send strategies; return True on first success."""

    # Strategy 1: role=button with name "Send"
    try:
        btn = page.get_by_role(
            "button", name=re.compile(r"^send( message)?$", re.I)
        ).first
        if await btn.is_visible(timeout=3000):
            print("[offerup-msg] send: role=button name=Send")
            await btn.click()
            return True
    except Exception as e:
        print(f"[offerup-msg] strategy 1 failed: {e}")

    # Strategy 2: button with Send text
    try:
        btn = page.locator('button:has-text("Send")').first
        if await btn.is_visible(timeout=2000):
            print("[offerup-msg] send: button:has-text(Send)")
            await btn.click()
            return True
    except Exception as e:
        print(f"[offerup-msg] strategy 2 failed: {e}")

    # Strategy 3: aria-label="Send"
    try:
        btn = page.locator('[aria-label="Send"]').first
        if await btn.is_visible(timeout=2000):
            print("[offerup-msg] send: [aria-label=Send]")
            await btn.click()
            return True
    except Exception as e:
        print(f"[offerup-msg] strategy 3 failed: {e}")

    # Strategy 4: Submit button (OfferUp sometimes uses form submission)
    try:
        btn = page.locator('button[type="submit"]').first
        if await btn.is_visible(timeout=2000):
            print("[offerup-msg] send: button[type=submit]")
            await btn.click()
            return True
    except Exception as e:
        print(f"[offerup-msg] strategy 4 failed: {e}")

    # Strategy 5: keyboard Enter
    try:
        print("[offerup-msg] send: Enter")
        await composer.press("Enter")
        return True
    except Exception as e:
        print(f"[offerup-msg] strategy 5 failed: {e}")

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
            --remote-debugging-port=9222.
        warmup: if True, browse offerup.com briefly before going to
            the listing.

    Returns {"success": bool, "error": str | None}.
    """
    async with async_playwright() as p:
        close_context = True
        try:
            if cdp:
                context = await attach_to_user_chrome(p, cdp_url)
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
            await asyncio.sleep(5)
            await _snap(page, "offerup_00_after_load")

            await _open_composer(page)
            await _fill_and_send(page, message_text)
            await asyncio.sleep(3)

            return {"success": True, "error": None}
        except Exception as e:
            return {"success": False, "error": f"{type(e).__name__}: {e}"}
        finally:
            if close_context:
                await context.close()


async def _main() -> None:
    parser = argparse.ArgumentParser(description="Message an OfferUp seller.")
    parser.add_argument("listing_url", help="OfferUp item detail URL")
    parser.add_argument("message", help="Message body to send")
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="Attach to a Chrome started with --remote-debugging-port=9222",
    )
    parser.add_argument(
        "--cdp-url",
        default="http://localhost:9222",
        help="CDP endpoint for --cdp mode (default: http://localhost:9222)",
    )
    parser.add_argument(
        "--no-warmup",
        action="store_true",
        help="Skip the warm-up browse before the listing nav",
    )
    args = parser.parse_args()

    print(f"[offerup-msg] {args.listing_url}")
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
