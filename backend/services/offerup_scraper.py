"""OfferUp scraper CLI and service wrapper.

The active scraper path is the GraphQL implementation in
``backend.services.offerup_graphql``. This module keeps the command-line entry
point, but intentionally does not include the older browser/DOM card scraping
fallback.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from backend.services.offerup_graphql import DEFAULT_MIN_PRICE


async def search_offerup(
    query: str,
    *,
    min_price: int | None = DEFAULT_MIN_PRICE,
    max_price: int | None = None,
    max_results: int = 30,
    location: str | None = None,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """Run a single OfferUp search through the GraphQL scraper."""
    from backend.services.offerup_graphql import search_offerup_graphql

    return await search_offerup_graphql(
        query,
        min_price=min_price,
        max_price=max_price,
        max_results=max_results,
        location=location,
        include_details=include_details,
        # Lower than the graphql default (5). Parallel detail fetches were
        # the main reason OfferUp 429'd us mid-job — pacing them keeps the
        # scrape under the throttle.
        detail_concurrency=2,
    )


async def get_offerup_listing_detail(item: str | dict[str, Any]) -> dict[str, Any]:
    """Fetch full details for an OfferUp listing id, URL, or search result."""
    from backend.services.offerup_graphql import get_offerup_listing_detail as get_detail

    return await get_detail(item)


async def _ingest_results(
    listings: list[dict[str, Any]],
    *,
    search_query: str,
    hobby: str | None,
    item_type: str | None = None,
) -> dict[str, int]:
    from backend.services.listing_store import upsert_scraped_listings

    return await upsert_scraped_listings(
        listings,
        search_query=search_query,
        hobby=hobby,
        item_type=item_type,
        source="offerup",
    )


async def _main() -> None:
    parser = argparse.ArgumentParser(description="OfferUp scraper.")
    parser.add_argument(
        "query",
        help="OfferUp search query",
    )
    parser.add_argument("--max-price", type=int, default=None, help="USD price ceiling")
    parser.add_argument(
        "--min-price",
        type=int,
        default=DEFAULT_MIN_PRICE,
        help="USD price floor; defaults to 2 to skip $0/$1 bait listings",
    )
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument(
        "--location",
        default=None,
        help="Override search location with a known city, ZIP code, or lat/lon.",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Skip per-listing detail pages and return feed data only.",
    )
    parser.add_argument("--save", default=None, help="Optional path to write JSON output")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="After scraping, upsert directly into MongoDB.",
    )
    parser.add_argument(
        "--hobby",
        default=None,
        help="Optional hobby metadata for ingest.",
    )
    args = parser.parse_args()

    include_details = not args.no_details
    print(
        f"[offerup-scraper] query={args.query!r} "
        f"minPrice={args.min_price} maxPrice={args.max_price}"
    )
    listing_results = await search_offerup(
        query=args.query,
        min_price=args.min_price,
        max_price=args.max_price,
        max_results=args.max_results,
        location=args.location,
        include_details=include_details,
    )

    print(f"[offerup-scraper] got {len(listing_results)} listings total")
    output = {
        "query": {
            "query": args.query,
            "minPrice": args.min_price,
            "maxPrice": args.max_price,
        },
        "listings": listing_results,
    }

    if args.save:
        Path(args.save).write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"[offerup-scraper] saved to {args.save}")

    if args.ingest:
        totals = await _ingest_results(
            listing_results,
            search_query=args.query,
            hobby=args.hobby,
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
