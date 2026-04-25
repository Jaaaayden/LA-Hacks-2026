"""Ingest scraper output JSON into the listings collection.

Reads files produced by `scripts/run_scrape.js` (or the future Python scraper),
normalizes each listing to the Listing schema, and upserts into MongoDB keyed
on fb_id. Idempotent: re-running on the same file produces 0 new inserts.

Usage:
    python -m backend.services.ingest scraper/output/2026-04-25T10-50-05-907Z_snowboard.json
    python -m backend.services.ingest scraper/output/*.json
    python -m backend.services.ingest scraper/output/some.json --hobby snowboarding
"""

import argparse
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from kitscout.db import listings
from kitscout.schemas import Listing, Location

_FB_ID_RE = re.compile(r"/marketplace/item/(\d+)")

_HOBBY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "snowboarding": ("snowboard", "ski goggles", "snowboarding"),
    "skateboarding": ("skateboard", "skating", "skate deck"),
    "photography": ("camera", "lens", "tripod", "photo"),
}

_SNOWBOARDING_ITEMS: tuple[tuple[str, str], ...] = (
    ("boots", "boots"),
    ("boot", "boots"),
    ("bindings", "bindings"),
    ("binding", "bindings"),
    ("helmet", "helmet"),
    ("goggles", "goggles"),
    ("jacket", "jacket"),
    ("pants", "pants"),
)


def parse_fb_id(url: str) -> str | None:
    if not url:
        return None
    m = _FB_ID_RE.search(url)
    return m.group(1) if m else None


def parse_location(raw: str | None) -> Location:
    if not raw:
        return Location()
    parts = [p.strip() for p in raw.split(",", 1)]
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        return Location(city=parts[0] or None, state=parts[1].upper(), raw=raw)
    return Location(city=parts[0] or None, raw=raw)


def infer_hobby(query: str) -> str:
    text = query.lower()
    for hobby, keywords in _HOBBY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return hobby
    return "unknown"


def classify_item_type(title: str, query: str, hobby: str) -> str:
    text = f"{title} {query}".lower()
    if hobby == "snowboarding":
        for keyword, item_type in _SNOWBOARDING_ITEMS:
            if keyword in text:
                return item_type
        return "board"
    return "unknown"


def to_listing(
    scraped: dict,
    *,
    hobby: str,
    query: str,
    scraped_at: datetime,
) -> Listing | None:
    url = scraped.get("url") or ""
    fb_id = parse_fb_id(url)
    if not fb_id:
        return None

    img = scraped.get("imageUrl") or scraped.get("image_url")
    if img and not str(img).startswith("http"):
        img = None

    try:
        return Listing(
            fb_id=fb_id,
            url=url,
            title=scraped.get("title") or "",
            price_usd=float(scraped.get("price") or 0),
            hobby=hobby,
            item_type=classify_item_type(scraped.get("title", ""), query, hobby),
            location=parse_location(scraped.get("location")),
            image_url=img,
            scraped_at=scraped_at,
            raw=scraped,
        )
    except Exception:
        return None


async def ingest_listings(
    scraped: list[dict],
    *,
    query: str = "",
    hobby: str | None = None,
    scraped_at: datetime | None = None,
) -> dict[str, int]:
    """Upsert in-memory listings (e.g. from the live scraper) into MongoDB."""
    resolved_hobby = hobby or infer_hobby(query)
    resolved_scraped_at = scraped_at or datetime.now(timezone.utc)

    counts = {"inserted": 0, "matched": 0, "skipped": 0}
    for raw in scraped:
        listing = to_listing(
            raw,
            hobby=resolved_hobby,
            query=query,
            scraped_at=resolved_scraped_at,
        )
        if listing is None:
            counts["skipped"] += 1
            continue

        result = await listings.update_one(
            {"fb_id": listing.fb_id},
            {"$set": listing.model_dump()},
            upsert=True,
        )
        if result.upserted_id is not None:
            counts["inserted"] += 1
        else:
            counts["matched"] += 1

    return counts


async def ingest_file(
    path: str | Path,
    *,
    hobby: str | None = None,
) -> dict[str, int]:
    path = Path(path)
    data = json.loads(path.read_text())

    query_obj = data.get("query") or {}
    query_str = query_obj.get("query", "")
    scraped_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)

    return await ingest_listings(
        data.get("listings", []),
        query=query_str,
        hobby=hobby,
        scraped_at=scraped_at,
    )


async def _main(paths: list[str], hobby: str | None) -> None:
    total = {"inserted": 0, "matched": 0, "skipped": 0}
    for p in paths:
        print(f"\n[ingest] {p}")
        result = await ingest_file(p, hobby=hobby)
        print(
            f"  inserted={result['inserted']}  "
            f"matched={result['matched']}  "
            f"skipped={result['skipped']}"
        )
        for k in total:
            total[k] += result[k]
    print(
        f"\n[ingest] TOTAL: inserted={total['inserted']}  "
        f"matched={total['matched']}  skipped={total['skipped']}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest scraper JSON into MongoDB.")
    parser.add_argument("paths", nargs="+", help="Scraper output JSON files")
    parser.add_argument(
        "--hobby",
        default=None,
        help="Override hobby (default: inferred from query)",
    )
    args = parser.parse_args()

    asyncio.run(_main(args.paths, args.hobby))
