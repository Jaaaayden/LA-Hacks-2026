"""Facebook Marketplace scraper — local Chrome via Playwright + Claude DOM-text extraction.

Drives the same persistent Chrome profile that `node scripts/fb_login.js`
populates, so we use the user's own IP (avoids FB's "Verify your location"
block on Browserbase egress IPs).

Two modes:
- single query  — `python -m backend.services.scraper "snowboard"`
- kit (hobby)   — `python -m backend.services.scraper --kit snowboarding`
  iterates a hardcoded list of complementary queries (board + boots + bindings
  + goggles + helmet) in one browser session and tags each listing with its
  item_type. Mirrors the old run_scrape.js multi-query flow.

Usage:
    # Single search
    python -m backend.services.scraper "snowboard" --city losangeles --max-price 300

    # Full kit for a hobby
    python -m backend.services.scraper --kit snowboarding --ingest

    # Single + upsert directly into MongoDB
    python -m backend.services.scraper "snowboard" --max-price 300 --ingest

    # Save to disk
    python -m backend.services.scraper "snowboard" --save out.json
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from pydantic import BaseModel

from backend.services._browser import launch_logged_in_chrome

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

IMAGES_DIR = Path("scraper/output/images")
DEBUG_DIR = Path("scraper/output/debug")
DEFAULT_IMAGE_CAPTURE_LIMIT = 12

_FB_ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)")

_EXTRACT_TOOL_NAME = "return_listings"

# Hardcoded kit definitions — same shape as the old run_scrape.js QUERIES list.
# Each slot becomes one Marketplace search; results are tagged with item_type
# so the ranker can build a curated kit (one of each slot under total budget).
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
    m = _FB_ITEM_ID_RE.search(url)
    return m.group(1) if m else None


async def _collect_card_blobs(page, *, max_results: int) -> list[dict]:
    """Walk the rendered DOM for marketplace item cards, return raw text per card.

    Each FB Marketplace card on a search results page is built around an
    <a href="/marketplace/item/<id>"> tag. The text inside that anchor (or
    its nearest grid-cell ancestor) carries title, price, location, and
    distance — predictable enough that we can hand structured TEXT to Claude
    instead of 1MB of raw HTML full of inline CSS/SVG noise.
    """
    anchors = page.locator('a[href*="/marketplace/item/"]')
    count = await anchors.count()
    print(f"[scraper] DOM: {count} candidate item anchors")

    blobs: list[dict] = []
    seen: set[str] = set()

    for i in range(count):
        if len(blobs) >= max_results * 2:
            # gather a bit extra to absorb dedup loss
            break
        anchor = anchors.nth(i)
        try:
            href = await anchor.get_attribute("href")
            if not href:
                continue
            m = _FB_ITEM_ID_RE.search(href)
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

            blobs.append(
                {
                    "platform_id": platform_id,
                    "url": f"https://www.facebook.com/marketplace/item/{platform_id}/",
                    "text": text,
                    "image_url": img if (img and img.startswith("https://")) else None,
                }
            )
        except Exception as e:
            print(f"[scraper] card {i} skipped: {e}")
            continue

    return blobs


async def _structure_via_claude(blobs: list[dict], *, max_results: int) -> list[dict]:
    """Hand per-card text to Haiku, get back title/price/location for each.

    Far fewer tokens and fewer hallucinations than feeding raw HTML.
    """
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
        "You are parsing Facebook Marketplace listing card text. Each input card "
        "has a platform_id and a multi-line text blob. From the text, infer:\n"
        "- title: the listing's product/item title (the most descriptive line)\n"
        "- price: numeric USD price; 0 for 'Free'; strip any '$' and commas\n"
        "- location: the city/area text shown (often the last or second-to-last line)\n"
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
        print("[scraper] Claude returned no structured listings")
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


async def _capture_hero_image(page, listing_url: str, platform_id: str, images_dir: Path) -> str | None:
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
        print(f"[scraper] screenshot failed for {platform_id}: {e}")
        return None


async def _run_one_search(
    page,
    query: str,
    *,
    city: str,
    max_price: int | None,
    max_results: int,
    scrolls: int,
    capture_images: int,
    item_type: str | None = None,
    snap_label: str = "scraper_search",
) -> list[dict]:
    """Drive an existing `page` through one Marketplace search query.

    Extracted so kit mode can reuse the same browser context across multiple
    queries — closing/reopening Chrome for every slot would burn ~10s each.
    """
    params = [f"query={query}"]
    if max_price is not None:
        params.append(f"maxPrice={max_price}")
    search_url = f"https://www.facebook.com/marketplace/{city}/search/?" + "&".join(params)

    print(f"[scraper] === {query!r} (max ${max_price}) ===")
    await page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(5)

    for sel in (
        '[aria-label="Close"]',
        '[aria-label="Decline optional cookies"]',
        '[aria-label="Allow all cookies"]',
    ):
        try:
            await page.locator(sel).first.click(timeout=1500)
            await asyncio.sleep(0.5)
        except Exception:
            pass

    try:
        await page.locator('a[href*="/marketplace/item/"]').first.wait_for(
            state="visible", timeout=20000
        )
    except Exception:
        print(f"[scraper] WARN: no listing cards for {query!r}")

    for _ in range(scrolls):
        await page.mouse.wheel(0, 1500)
        await asyncio.sleep(2)

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    await page.screenshot(path=str(DEBUG_DIR / f"{snap_label}.png"), full_page=False)

    blobs = await _collect_card_blobs(page, max_results=max_results)
    print(f"[scraper] DOM: {len(blobs)} unique cards")

    listings = await _structure_via_claude(blobs, max_results=max_results)
    listings = listings[:max_results]
    print(f"[scraper] extracted {len(listings)} listings for {query!r}")

    # Tag with the kit slot's item_type so ingest doesn't have to guess
    if item_type:
        for l in listings:
            l["item_type"] = item_type

    if capture_images > 0 and listings:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        for listing in listings[:capture_images]:
            platform_id = _platform_id_from_url(listing.get("url", ""))
            if not platform_id:
                continue
            path = await _capture_hero_image(page, listing["url"], platform_id, IMAGES_DIR)
            if path:
                listing["image_path"] = path
            await asyncio.sleep(1)

    return listings


async def search_marketplace(
    query: str,
    *,
    city: str = "losangeles",
    max_price: int | None = None,
    max_results: int = 30,
    scrolls: int = 2,
    capture_images: int = DEFAULT_IMAGE_CAPTURE_LIMIT,
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
                city=city,
                max_price=max_price,
                max_results=max_results,
                scrolls=scrolls,
                capture_images=capture_images,
            )
        finally:
            await context.close()


async def search_kit(
    hobby: str,
    *,
    city: str = "losangeles",
    max_results_per_slot: int = 15,
    scrolls: int = 2,
    capture_images_per_slot: int = 5,
) -> list[dict]:
    """Run every kit slot for `hobby` in one Chrome session and merge results.

    Each returned listing carries an `item_type` tag matching its kit slot
    (board, boots, bindings, etc.) so the ranker can build a curated kit.
    Mirrors the old run_scrape.js multi-query loop.
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
                listings = await _run_one_search(
                    page,
                    slot["query"],
                    city=city,
                    max_price=slot.get("max_price"),
                    max_results=max_results_per_slot,
                    scrolls=scrolls,
                    capture_images=capture_images_per_slot,
                    item_type=slot["item_type"],
                    snap_label=f"scraper_search_{slot['item_type']}",
                )
                all_listings.extend(listings)
        finally:
            await context.close()

    return all_listings


async def _main() -> None:
    parser = argparse.ArgumentParser(description="FB Marketplace scraper (local Chrome).")
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
    parser.add_argument("--city", default="losangeles", help="City slug (default: losangeles)")
    parser.add_argument("--max-price", type=int, default=None, help="USD price ceiling (single-query mode)")
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
    parser.add_argument("--save", default=None, help="Optional path to write JSON output")
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
        print(f"[scraper] kit mode: {args.kit} city={args.city}")
        listings = await search_kit(
            args.kit,
            city=args.city,
            max_results_per_slot=args.per_slot_results,
            scrolls=args.scrolls,
            capture_images_per_slot=args.per_slot_images,
        )
        query_label = f"kit:{args.kit}"
        ingest_query = args.kit
        ingest_hobby = args.hobby or args.kit
    else:
        print(f"[scraper] query={args.query!r} city={args.city} maxPrice={args.max_price}")
        listings = await search_marketplace(
            query=args.query,
            city=args.city,
            max_price=args.max_price,
            max_results=args.max_results,
            scrolls=args.scrolls,
            capture_images=args.capture_images,
        )
        query_label = args.query
        ingest_query = args.query
        ingest_hobby = args.hobby

    print(f"[scraper] got {len(listings)} listings total")

    output = {
        "query": {"query": query_label, "city": args.city, "maxPrice": args.max_price},
        "listings": listings,
    }

    if args.save:
        Path(args.save).write_text(json.dumps(output, indent=2))
        print(f"[scraper] saved to {args.save}")

    if args.ingest:
        from backend.services.listing_store import upsert_scraped_listings

        totals = {"inserted": 0, "matched": 0, "skipped": 0}
        if args.kit:
            # Kit mode: each listing already carries item_type from its slot.
            # Group by item_type and upsert per group so listing_store can
            # respect the slot's classification instead of running its
            # title-heuristic fallback.
            by_slot: dict[str | None, list[dict]] = {}
            for l in listings:
                by_slot.setdefault(l.get("item_type"), []).append(l)
            for slot_type, slot_listings in by_slot.items():
                result = await upsert_scraped_listings(
                    slot_listings,
                    search_query=ingest_query,
                    hobby=ingest_hobby,
                    shopping_list_item_type=slot_type,
                )
                for k in totals:
                    totals[k] += result[k]
        else:
            totals = await upsert_scraped_listings(
                listings,
                search_query=ingest_query,
                hobby=ingest_hobby,
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
