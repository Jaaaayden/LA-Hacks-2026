"""Facebook Marketplace scraper (Python port of scraper/facebook.js + scripts/run_scrape.js).

Uses Browserbase + Stagehand. Requires a populated FB_CONTEXT_ID — create one
by running `node scripts/fb_login.js` (kept in JS because it needs interactive
URL polling that the Python SDK's high-level abstraction doesn't expose).

Usage:
    # Scrape and print JSON to stdout
    python -m backend.services.scraper "snowboard" --city losangeles --max-price 300

    # Scrape and upsert directly into MongoDB
    python -m backend.services.scraper "snowboard" --max-price 300 --ingest

    # Scrape and save to disk (matches the JS scraper's output shape)
    python -m backend.services.scraper "snowboard" --save out.json
"""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from browserbase import AsyncBrowserbase
from dotenv import load_dotenv
from playwright.async_api import async_playwright
from pydantic import BaseModel
from stagehand import AsyncStagehand

load_dotenv()

DEFAULT_MODEL = "anthropic/claude-sonnet-4-5"

IMAGES_DIR = Path("scraper/output/images")
DEFAULT_IMAGE_CAPTURE_LIMIT = 12

_FB_ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)")


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


def _fb_id_from_url(url: str) -> str | None:
    if not url:
        return None
    m = _FB_ITEM_ID_RE.search(url)
    return m.group(1) if m else None


async def _resolve_cdp_page(bb_api_key: str, session_id: str, browser):
    """Find the active page on the connected CDP browser.

    Returns a Playwright Page or None.
    """
    contexts = browser.contexts
    if not contexts or not contexts[0].pages:
        return None
    return contexts[0].pages[-1]


async def _capture_hero_image(
    client: "AsyncStagehand",
    session_id: str,
    listing_url: str,
    fb_id: str,
    *,
    images_dir: Path,
    page,
) -> str | None:
    """Navigate to a listing detail page and save a viewport screenshot.

    `page` is a persistent Playwright Page connected over CDP to the same
    Browserbase session Stagehand is driving — reused across all listings to
    avoid per-call connect/disconnect overhead.

    Returns the local image path string on success, or None on failure.
    """
    img_path = images_dir / f"{fb_id}.png"
    if img_path.exists():
        return str(img_path)

    try:
        await client.sessions.navigate(session_id, url=listing_url)
        await asyncio.sleep(2)

        png_bytes = await page.screenshot(type="png", full_page=False)
        if not png_bytes:
            return None

        img_path.write_bytes(png_bytes)
        return str(img_path)
    except Exception as e:
        print(f"[scraper] screenshot failed for {fb_id}: {e}")
        return None


async def search_marketplace(
    query: str,
    *,
    city: str = "losangeles",
    max_price: int | None = None,
    max_results: int = 30,
    scrolls: int = 2,
    model_name: str = DEFAULT_MODEL,
    capture_images: int = DEFAULT_IMAGE_CAPTURE_LIMIT,
) -> list[dict]:
    """Search FB Marketplace and return up to `max_results` listings as plain dicts.

    Each listing dict has: title, price, location, url, image_url, and (when
    `capture_images > 0`) image_path.
    `image_url` may be a non-http garbage value (Stagehand bug) — the ingester
    filters those to None at validation time. `image_path` is the trustworthy
    source for the frontend: the first `capture_images` listings are visited
    individually and their hero photo downloaded to scraper/output/images/.
    """
    bb_api_key = _require_env("BROWSERBASE_API_KEY")
    bb_project_id = _require_env("BROWSERBASE_PROJECT_ID")
    fb_context_id = _require_env("FB_CONTEXT_ID")
    anthropic_key = _require_env("ANTHROPIC_API_KEY")

    params = [f"query={query}"]
    if max_price is not None:
        params.append(f"maxPrice={max_price}")
    url = f"https://www.facebook.com/marketplace/{city}/search/?" + "&".join(params)

    async with AsyncStagehand(
        browserbase_api_key=bb_api_key,
        browserbase_project_id=bb_project_id,
        model_api_key=anthropic_key,
    ) as client:
        start = await client.sessions.start(
            model_name=model_name,
            browserbase_session_create_params={
                "project_id": bb_project_id,
                "browser_settings": {
                    "context": {"id": fb_context_id, "persist": False},
                },
            },
        )
        session_id = start.data.session_id

        try:
            await client.sessions.navigate(session_id, url=url)
            await asyncio.sleep(3)

            await client.sessions.act(
                session_id,
                input="dismiss any login or cookie modal if present",
            )

            for _ in range(scrolls):
                await client.sessions.act(
                    session_id,
                    input="scroll down to load more marketplace listings",
                )
                await asyncio.sleep(2)

            response = await client.sessions.extract(
                session_id,
                instruction=(
                    "Extract every visible Facebook Marketplace listing card on this page. "
                    "For each card, read these from the actual rendered HTML:\n"
                    "- title: listing title text\n"
                    "- price: numeric USD price (0 if free)\n"
                    "- location: location text under the title\n"
                    "- url: the <a> tag's href, must start with "
                    "'https://www.facebook.com/marketplace/item/'\n"
                    "- image_url: the literal value of the src attribute on the listing's "
                    "<img> element. This MUST be a complete URL beginning with 'https://' "
                    "(typically 'https://scontent' or 'https://external'). If the src is "
                    "missing, a data: URI, a relative path, or anything not starting with "
                    "'https://', return null. NEVER return element references, CSS selectors, "
                    "sibling indices, numbered identifiers like '1-25', or any internal "
                    "annotation — only the literal string value of the src attribute."
                ),
                schema=_ScrapedListings.model_json_schema(),
            )

            response_dict = (
                response.model_dump() if hasattr(response, "model_dump") else response
            )
            raw_listings = (
                (response_dict.get("data") or {}).get("result", {}).get("listings", [])
                or []
            )
            raw_listings = raw_listings[:max_results]

            if capture_images > 0 and raw_listings:
                IMAGES_DIR.mkdir(parents=True, exist_ok=True)

                async with AsyncBrowserbase(api_key=bb_api_key) as bb:
                    urls = await bb.sessions.debug(session_id)
                    ws_url = urls.ws_url

                async with async_playwright() as p:
                    browser = await p.chromium.connect_over_cdp(ws_url)
                    try:
                        page = await _resolve_cdp_page(bb_api_key, session_id, browser)
                        if page is None:
                            print("[scraper] CDP: no page found; skipping image capture")
                        else:
                            for listing in raw_listings[:capture_images]:
                                fb_id = _fb_id_from_url(listing.get("url", ""))
                                if not fb_id:
                                    continue
                                path = await _capture_hero_image(
                                    client,
                                    session_id,
                                    listing["url"],
                                    fb_id,
                                    images_dir=IMAGES_DIR,
                                    page=page,
                                )
                                if path:
                                    listing["image_path"] = path
                                await asyncio.sleep(1)
                    finally:
                        await browser.close()
        finally:
            await client.sessions.end(session_id)

    return raw_listings


async def _main() -> None:
    parser = argparse.ArgumentParser(description="FB Marketplace scraper (Python).")
    parser.add_argument("query", help="Search query, e.g. 'snowboard'")
    parser.add_argument("--city", default="losangeles", help="City slug (default: losangeles)")
    parser.add_argument("--max-price", type=int, default=None, help="USD price ceiling")
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument("--scrolls", type=int, default=2)
    parser.add_argument(
        "--capture-images",
        type=int,
        default=DEFAULT_IMAGE_CAPTURE_LIMIT,
        help="Visit top N listings and save hero photos to scraper/output/images/ (0 to disable)",
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
        help="Override hobby for ingest (default: inferred from query)",
    )
    args = parser.parse_args()

    print(f"[scraper] query={args.query!r} city={args.city} maxPrice={args.max_price}")
    listings = await search_marketplace(
        query=args.query,
        city=args.city,
        max_price=args.max_price,
        max_results=args.max_results,
        scrolls=args.scrolls,
        capture_images=args.capture_images,
    )
    print(f"[scraper] got {len(listings)} listings")

    output = {
        "query": {"query": args.query, "city": args.city, "maxPrice": args.max_price},
        "listings": listings,
    }

    if args.save:
        Path(args.save).write_text(json.dumps(output, indent=2))
        print(f"[scraper] saved to {args.save}")

    if args.ingest:
        from backend.services.listing_store import upsert_scraped_listings

        result = await upsert_scraped_listings(
            listings,
            search_query=args.query,
            hobby=args.hobby,
        )
        print(
            f"[ingest] inserted={result['inserted']}  "
            f"matched={result['matched']}  "
            f"skipped={result['skipped']}"
        )

    if not args.save and not args.ingest:
        print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
