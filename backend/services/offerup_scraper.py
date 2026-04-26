"""OfferUp scraper — local Chrome via Playwright + Claude DOM-text extraction.

Drives a persistent Chrome profile populated by `python scripts/offerup_login.py`.

OfferUp search URLs use `offerup.com/search?q=<query>`. Price filtering is
done via the on-page filter UI (no URL param), so we interact with the filter
controls programmatically.

Two modes:
- single query  — `python -m backend.services.offerup_scraper "snowboard"`
- kit (hobby)   — `python -m backend.services.offerup_scraper --kit snowboarding`

Usage:
    # Single search
    python -m backend.services.offerup_scraper "snowboard" --max-price 300

    # Full kit for a hobby
    python -m backend.services.offerup_scraper --kit snowboarding --ingest

    # Save to disk
    python -m backend.services.offerup_scraper "snowboard" --save out.json
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from playwright.async_api import Page, async_playwright
from pydantic import BaseModel

from backend.services._browser_offerup import launch_logged_in_chrome

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

IMAGES_DIR = Path("scraper/output/images_offerup")
DEBUG_DIR = Path("scraper/output/debug")
DEFAULT_IMAGE_CAPTURE_LIMIT = 12

_OFFERUP_ITEM_ID_RE = re.compile(r"/item/detail/(\d+)")

_EXTRACT_TOOL_NAME = "return_listings"

# Same kit definitions as the FB scraper — reusable across platforms.
KIT_QUERIES: dict[str, list[dict]] = {
    "snowboarding": [
        {"item_type": "board", "query": "snowboard", "max_price": 300},
        {"item_type": "boots", "query": "snowboard boots", "max_price": 150},
        {"item_type": "bindings", "query": "snowboard bindings", "max_price": 120},
        {"item_type": "goggles", "query": "ski goggles", "max_price": 60},
        {"item_type": "helmet", "query": "snowboard helmet", "max_price": 80},
    ],
    "skateboarding": [
        {"item_type": "deck", "query": "skateboard deck", "max_price": 80},
        {"item_type": "trucks", "query": "skateboard trucks", "max_price": 50},
        {"item_type": "wheels", "query": "skateboard wheels", "max_price": 40},
        {"item_type": "helmet", "query": "skateboard helmet", "max_price": 60},
    ],
    "photography": [
        {"item_type": "camera", "query": "dslr camera", "max_price": 400},
        {"item_type": "lens", "query": "camera lens 50mm", "max_price": 200},
        {"item_type": "tripod", "query": "camera tripod", "max_price": 80},
        {"item_type": "bag", "query": "camera bag", "max_price": 60},
    ],
}


class _ScrapedListing(BaseModel):
    title: str
    price: float
    location: str
    url: str
    image_url: str | None = None


class _ScrapedListings(BaseModel):
    listings: list[_ScrapedListing]


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


def _platform_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = _OFFERUP_ITEM_ID_RE.search(url)
    return m.group(1) if m else None


async def _apply_price_filter(page: Page, max_price: int) -> None:
    """Interact with OfferUp's filter UI to set a max price.

    OfferUp doesn't support price filters via URL params — we need to click
    the filter controls on the search results page. The exact selectors may
    change, so we try multiple strategies.
    """
    print(f"[offerup-scraper] applying price filter: max ${max_price}")

    # Strategy 1: Look for a "Price" filter button and interact
    try:
        # OfferUp typically has filter buttons at the top of search results
        price_btn = page.locator(
            'button:has-text("Price"), '
            '[data-testid*="price" i], '
            'button:has-text("Filter")'
        ).first
        if await price_btn.is_visible(timeout=3000):
            await price_btn.click()
            await asyncio.sleep(1)

            # Look for max price input
            max_input = page.locator(
                'input[placeholder*="Max" i], '
                'input[aria-label*="max" i], '
                'input[name*="max" i], '
                'input[placeholder*="To" i]'
            ).first
            if await max_input.is_visible(timeout=2000):
                await max_input.click()
                await max_input.fill(str(max_price))
                await asyncio.sleep(0.5)

                # Click apply/done
                apply_btn = page.locator(
                    'button:has-text("Apply"), '
                    'button:has-text("Done"), '
                    'button:has-text("Show")'
                ).first
                if await apply_btn.is_visible(timeout=2000):
                    await apply_btn.click()
                    await asyncio.sleep(2)
                    print("[offerup-scraper] price filter applied via UI")
                    return
    except Exception as e:
        print(f"[offerup-scraper] price filter strategy 1 failed: {e}")

    # Strategy 2: Try URL-based filtering (some OfferUp versions support it)
    try:
        current_url = page.url
        if "?" in current_url:
            new_url = f"{current_url}&price_max={max_price}"
        else:
            new_url = f"{current_url}?price_max={max_price}"
        await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(3)
        print("[offerup-scraper] tried URL-based price filter")
    except Exception as e:
        print(f"[offerup-scraper] price filter strategy 2 failed: {e}")

    print("[offerup-scraper] price filter may not have been applied — will rely on Claude to filter")


async def _set_location(page: Page, location: str) -> None:
    """Override OfferUp's search location via the location UI.

    Called when the user specifies a location in their prompt.
    """
    print(f"[offerup-scraper] setting location: {location}")
    try:
        # Look for location/area selector — usually at top of page
        loc_btn = page.locator(
            'button:has-text("Location"), '
            '[data-testid*="location" i], '
            'button[aria-label*="location" i], '
            'a:has-text("Change location")'
        ).first
        if await loc_btn.is_visible(timeout=3000):
            await loc_btn.click()
            await asyncio.sleep(1)

            # Find location input and type
            loc_input = page.locator(
                'input[placeholder*="zip" i], '
                'input[placeholder*="city" i], '
                'input[placeholder*="location" i], '
                'input[aria-label*="location" i]'
            ).first
            if await loc_input.is_visible(timeout=2000):
                await loc_input.click()
                await loc_input.fill("")
                await loc_input.type(location, delay=50)
                await asyncio.sleep(2)

                # Click first suggestion
                suggestion = page.locator(
                    '[role="option"]:first-child, '
                    '[data-testid*="suggestion"]:first-child, '
                    'li:first-child'
                ).first
                if await suggestion.is_visible(timeout=3000):
                    await suggestion.click()
                    await asyncio.sleep(2)
                    print(f"[offerup-scraper] location set to: {location}")
                    return

        print("[offerup-scraper] location selector not found — using account default")
    except Exception as e:
        print(f"[offerup-scraper] set location failed: {e}")


async def _collect_card_blobs(page: Page, *, max_results: int) -> list[dict]:
    """Walk the rendered DOM for OfferUp listing cards, return raw text per card.

    OfferUp item cards link to /item/detail/<id>. We extract the text content,
    image URL, and link from each card.
    """
    # OfferUp uses various link patterns for item detail pages
    anchors = page.locator(
        'a[href*="/item/detail/"], '
        'a[href*="/item/"]'
    )
    count = await anchors.count()
    print(f"[offerup-scraper] DOM: {count} candidate item anchors")

    blobs: list[dict] = []
    seen: set[str] = set()

    for i in range(count):
        if len(blobs) >= max_results * 2:
            break
        anchor = anchors.nth(i)
        try:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            m = _OFFERUP_ITEM_ID_RE.search(href)
            if not m:
                continue
            platform_id = m.group(1)
            if platform_id in seen:
                continue
            seen.add(platform_id)

            text = (await anchor.inner_text()).strip()
            if not text:
                continue

            img = None
            try:
                img = await anchor.locator("img").first.get_attribute("src", timeout=500)
            except Exception:
                pass

            # Construct full URL if href is relative
            if href.startswith("/"):
                full_url = f"https://offerup.com{href}"
            elif href.startswith("http"):
                full_url = href
            else:
                full_url = f"https://offerup.com/item/detail/{platform_id}"

            blobs.append(
                {
                    "platform_id": platform_id,
                    "url": full_url,
                    "text": text,
                    "image_url": img if (img and img.startswith("https://")) else None,
                }
            )
        except Exception as e:
            print(f"[offerup-scraper] card {i} skipped: {e}")
            continue

    return blobs


async def _structure_via_claude(blobs: list[dict], *, max_results: int) -> list[dict]:
    """Hand per-card text to Haiku, get back title/price/location for each."""
    if not blobs:
        return []

    api_key = _require_env("ANTHROPIC_API_KEY")
    client = AsyncAnthropic(api_key=api_key)

    tool = {
        "name": _EXTRACT_TOOL_NAME,
        "description": "Return one structured listing object per input card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "listings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "platform_id": {"type": "string"},
                            "title": {"type": "string"},
                            "price": {"type": "number"},
                            "location": {"type": "string"},
                        },
                        "required": ["platform_id", "title", "price", "location"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["listings"],
            "additionalProperties": False,
        },
    }

    system = (
        "You are parsing OfferUp listing card text. Each input card "
        "has a platform_id and a multi-line text blob. From the text, infer:\n"
        "- title: the listing's product/item title (the most descriptive line)\n"
        "- price: numeric USD price; 0 for 'Free'; strip any '$' and commas\n"
        "- location: the city/area text shown (often includes distance like '5 mi away')\n"
        "Return ONE listing per input card, preserving platform_id. If you can't extract "
        "a field cleanly, use empty string for title/location, 0 for price."
    )

    user_payload = "\n\n".join(
        f"=== CARD platform_id={b['platform_id']} ===\n{b['text']}" for b in blobs[: max_results * 2]
    )

    response = await client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=4096,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": _EXTRACT_TOOL_NAME},
        messages=[{"role": "user", "content": user_payload}],
    )

    structured: dict[str, dict] = {}
    for block in response.content:
        if block.type == "tool_use" and block.name == _EXTRACT_TOOL_NAME:
            payload = block.input if isinstance(block.input, dict) else dict(block.input)
            for item in payload.get("listings", []):
                platform_id = item.get("platform_id")
                if platform_id:
                    structured[platform_id] = item
            break

    if not structured:
        print("[offerup-scraper] Claude returned no structured listings")
        return []

    # Merge back with the URL + image_url we got from the DOM
    out: list[dict] = []
    for blob in blobs:
        s = structured.get(blob["platform_id"])
        if not s:
            continue
        out.append(
            {
                "title": s.get("title", ""),
                "price": float(s.get("price") or 0),
                "location": s.get("location", ""),
                "url": blob["url"],
                "image_url": blob["image_url"],
            }
        )
        if len(out) >= max_results:
            break
    return out


async def _capture_hero_image(
    page: Page, listing_url: str, platform_id: str, images_dir: Path
) -> str | None:
    """Navigate `page` to a listing detail page and save a viewport screenshot."""
    img_path = images_dir / f"{platform_id}.png"
    if img_path.exists():
        return str(img_path)

    try:
        await page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        png_bytes = await page.screenshot(type="png", full_page=False)
        if not png_bytes:
            return None
        img_path.write_bytes(png_bytes)
        return str(img_path)
    except Exception as e:
        print(f"[offerup-scraper] screenshot failed for {platform_id}: {e}")
        return None


async def _run_one_search(
    page: Page,
    query: str,
    *,
    max_price: int | None,
    max_results: int,
    scrolls: int,
    capture_images: int,
    item_type: str | None = None,
    location: str | None = None,
    snap_label: str = "offerup_search",
) -> list[dict]:
    """Drive an existing `page` through one OfferUp search query."""

    # Build search URL
    search_url = f"https://offerup.com/search?q={query}"

    print(f"[offerup-scraper] === {query!r} (max ${max_price}) ===")
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(5)

    # Override location if user specified one
    if location:
        await _set_location(page, location)
        # Re-navigate after location change
        await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

    # Apply price filter if specified
    if max_price is not None:
        await _apply_price_filter(page, max_price)

    # Dismiss popups (cookie banners, app prompts, etc.)
    for sel in (
        '[aria-label="Close"]',
        '[aria-label="close"]',
        '[aria-label="Dismiss"]',
        'button:has-text("Got it")',
        'button:has-text("No thanks")',
        'button:has-text("Not now")',
    ):
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1500):
                await btn.click()
                await asyncio.sleep(0.5)
        except Exception:
            pass

    # Wait for listing cards to appear
    try:
        await page.locator('a[href*="/item/detail/"]').first.wait_for(
            state="visible", timeout=20000
        )
    except Exception:
        print(f"[offerup-scraper] WARN: no listing cards for {query!r}")

    # Scroll to load more results
    for _ in range(scrolls):
        await page.mouse.wheel(0, 1500)
        await asyncio.sleep(2)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(DEBUG_DIR / f"{snap_label}.png"), full_page=False)

    blobs = await _collect_card_blobs(page, max_results=max_results)
    print(f"[offerup-scraper] DOM: {len(blobs)} unique cards")

    listings = await _structure_via_claude(blobs, max_results=max_results)
    listings = listings[:max_results]
    print(f"[offerup-scraper] extracted {len(listings)} listings for {query!r}")

    # Tag with the kit slot's item_type
    if item_type:
        for l in listings:
            l["item_type"] = item_type

    if capture_images > 0 and listings:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        for listing in listings[:capture_images]:
            pid = _platform_id_from_url(listing.get("url", ""))
            if not pid:
                continue
            path = await _capture_hero_image(page, listing["url"], pid, IMAGES_DIR)
            if path:
                listing["image_path"] = path
            await asyncio.sleep(1)

    return listings


async def search_offerup(
    query: str,
    *,
    max_price: int | None = None,
    max_results: int = 30,
    scrolls: int = 2,
    capture_images: int = DEFAULT_IMAGE_CAPTURE_LIMIT,
    location: str | None = None,
) -> list[dict]:
    """Single-query search. Each listing has title, price, location, url,
    image_url, and (when `capture_images > 0`) image_path."""
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            return await _run_one_search(
                page,
                query,
                max_price=max_price,
                max_results=max_results,
                scrolls=scrolls,
                capture_images=capture_images,
                location=location,
            )
        finally:
            await context.close()


async def search_kit(
    hobby: str,
    *,
    max_results_per_slot: int = 15,
    scrolls: int = 2,
    capture_images_per_slot: int = 5,
    location: str | None = None,
) -> list[dict]:
    """Run every kit slot for `hobby` in one Chrome session and merge results.

    Each returned listing carries an `item_type` tag matching its kit slot.
    """
    queries = KIT_QUERIES.get(hobby)
    if not queries:
        raise ValueError(
            f"No kit defined for hobby={hobby!r}. "
            f"Known: {sorted(KIT_QUERIES.keys())}"
        )

    all_listings: list[dict] = []
    async with async_playwright() as p:
        context = await launch_logged_in_chrome(p)
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            for slot in queries:
                slot_listings = await _run_one_search(
                    page,
                    slot["query"],
                    max_price=slot.get("max_price"),
                    max_results=max_results_per_slot,
                    scrolls=scrolls,
                    capture_images=capture_images_per_slot,
                    item_type=slot["item_type"],
                    location=location,
                    snap_label=f"offerup_search_{slot['item_type']}",
                )
                all_listings.extend(slot_listings)
        finally:
            await context.close()

    return all_listings


async def _main() -> None:
    parser = argparse.ArgumentParser(description="OfferUp scraper (local Chrome).")
    parser.add_argument(
        "query",
        nargs="?",
        default=None,
        help="Single search query (omit when using --kit)",
    )
    parser.add_argument(
        "--kit",
        default=None,
        choices=sorted(KIT_QUERIES.keys()),
        help="Run all kit slots for this hobby instead of a single query",
    )
    parser.add_argument(
        "--max-price", type=int, default=None, help="USD price ceiling"
    )
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--scrolls", type=int, default=2)
    parser.add_argument(
        "--capture-images",
        type=int,
        default=DEFAULT_IMAGE_CAPTURE_LIMIT,
        help="Visit top N listings and save hero photos (single-query mode)",
    )
    parser.add_argument(
        "--per-slot-results",
        type=int,
        default=15,
        help="Listings to collect per kit slot (kit mode only)",
    )
    parser.add_argument(
        "--per-slot-images",
        type=int,
        default=5,
        help="Hero screenshots per kit slot (kit mode only)",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="Override search location (city name or ZIP code). "
        "If omitted, uses account default.",
    )
    parser.add_argument(
        "--save", default=None, help="Optional path to write JSON output"
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="After scraping, upsert directly into MongoDB via backend.services.listing_store",
    )
    parser.add_argument(
        "--hobby",
        default=None,
        help="Override hobby for ingest (default: --kit value, else inferred from query)",
    )
    args = parser.parse_args()

    if not args.query and not args.kit:
        parser.error("Provide a positional query or --kit <hobby>")
    if args.query and args.kit:
        parser.error("Use either a query or --kit, not both")

    if args.kit:
        print(f"[offerup-scraper] kit mode: {args.kit}")
        listing_results = await search_kit(
            args.kit,
            max_results_per_slot=args.per_slot_results,
            scrolls=args.scrolls,
            capture_images_per_slot=args.per_slot_images,
            location=args.location,
        )
        query_label = f"kit:{args.kit}"
        ingest_query = args.kit
        ingest_hobby = args.hobby or args.kit
    else:
        print(
            f"[offerup-scraper] query={args.query!r} maxPrice={args.max_price}"
        )
        listing_results = await search_offerup(
            query=args.query,
            max_price=args.max_price,
            max_results=args.max_results,
            scrolls=args.scrolls,
            capture_images=args.capture_images,
            location=args.location,
        )
        query_label = args.query
        ingest_query = args.query
        ingest_hobby = args.hobby

    print(f"[offerup-scraper] got {len(listing_results)} listings total")

    output = {
        "query": {"query": query_label, "maxPrice": args.max_price},
        "listings": listing_results,
    }

    if args.save:
        Path(args.save).write_text(json.dumps(output, indent=2))
        print(f"[offerup-scraper] saved to {args.save}")

    if args.ingest:
        from backend.services.listing_store import upsert_scraped_listings

        totals = {"inserted": 0, "matched": 0, "skipped": 0}
        if args.kit:
            by_slot: dict[str | None, list[dict]] = {}
            for l in listing_results:
                by_slot.setdefault(l.get("item_type"), []).append(l)
            for slot_type, slot_listings in by_slot.items():
                result = await upsert_scraped_listings(
                    slot_listings,
                    search_query=ingest_query,
                    hobby=ingest_hobby,
                    item_type=slot_type,
                    source="offerup",
                )
                for k in totals:
                    totals[k] += result[k]
        else:
            totals = await upsert_scraped_listings(
                listing_results,
                search_query=ingest_query,
                hobby=ingest_hobby,
                source="offerup",
            )
        print(
            f"[ingest] inserted={totals['inserted']}  "
            f"matched={totals['matched']}  "
            f"skipped={totals['skipped']}"
        )

    if not args.save and not args.ingest:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
