"""OfferUp scraper CLI and service wrapper.

The active scraper path is the GraphQL implementation in
``backend.services.offerup_graphql``. This module keeps the command-line entry
point and kit-query helpers, but intentionally does not include the older
browser/DOM card scraping fallback.
"""

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any


KIT_QUERIES: dict[str, list[dict[str, Any]]] = {
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


async def search_offerup(
    query: str,
    *,
    max_price: int | None = None,
    max_results: int = 30,
    location: str | None = None,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """Run a single OfferUp search through the GraphQL scraper."""
    from backend.services.offerup_graphql import search_offerup_graphql

    return await search_offerup_graphql(
        query,
        max_price=max_price,
        max_results=max_results,
        location=location,
        include_details=include_details,
    )


async def get_offerup_listing_detail(item: str | dict[str, Any]) -> dict[str, Any]:
    """Fetch full details for an OfferUp listing id, URL, or search result."""
    from backend.services.offerup_graphql import get_offerup_listing_detail as get_detail

    return await get_detail(item)


async def search_kit(
    hobby: str,
    *,
    max_results_per_slot: int = 30,
    location: str | None = None,
    include_details: bool = True,
) -> list[dict[str, Any]]:
    """Run every configured kit slot for a hobby through OfferUp GraphQL."""
    queries = KIT_QUERIES.get(hobby)
    if not queries:
        raise ValueError(
            f"No kit defined for hobby={hobby!r}. "
            f"Known: {sorted(KIT_QUERIES.keys())}"
        )

    all_listings: list[dict[str, Any]] = []
    for slot in queries:
        slot_listings = await search_offerup(
            slot["query"],
            max_price=slot.get("max_price"),
            max_results=max_results_per_slot,
            location=location,
            include_details=include_details,
        )
        for listing in slot_listings:
            listing["item_type"] = slot["item_type"]
            listing["search_query"] = slot["query"]
        all_listings.extend(slot_listings)

    return all_listings


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
    parser.add_argument("--max-price", type=int, default=None, help="USD price ceiling")
    parser.add_argument("--max-results", type=int, default=30)
    parser.add_argument(
        "--per-slot-results",
        type=int,
        default=30,
        help="Listings to collect per kit slot (kit mode only)",
    )
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
        help="Override hobby for ingest (default: --kit value, else inferred).",
    )
    args = parser.parse_args()

    if not args.query and not args.kit:
        parser.error("Provide a positional query or --kit <hobby>")
    if args.query and args.kit:
        parser.error("Use either a query or --kit, not both")

    include_details = not args.no_details
    if args.kit:
        print(f"[offerup-scraper] kit mode: {args.kit}")
        listing_results = await search_kit(
            args.kit,
            max_results_per_slot=args.per_slot_results,
            location=args.location,
            include_details=include_details,
        )
        query_label = f"kit:{args.kit}"
        ingest_hobby = args.hobby or args.kit
    else:
        print(f"[offerup-scraper] query={args.query!r} maxPrice={args.max_price}")
        listing_results = await search_offerup(
            query=args.query,
            max_price=args.max_price,
            max_results=args.max_results,
            location=args.location,
            include_details=include_details,
        )
        query_label = args.query
        ingest_hobby = args.hobby

    print(f"[offerup-scraper] got {len(listing_results)} listings total")
    output = {
        "query": {"query": query_label, "maxPrice": args.max_price},
        "listings": listing_results,
    }

    if args.save:
        Path(args.save).write_text(json.dumps(output, indent=2), encoding="utf-8")
        print(f"[offerup-scraper] saved to {args.save}")

    if args.ingest:
        totals = {"inserted": 0, "matched": 0, "skipped": 0}
        if args.kit:
            grouped: dict[tuple[str | None, str], list[dict[str, Any]]] = {}
            for listing in listing_results:
                key = (listing.get("item_type"), listing.get("search_query") or args.kit)
                grouped.setdefault(key, []).append(listing)
            for (item_type, search_query), slot_listings in grouped.items():
                result = await _ingest_results(
                    slot_listings,
                    search_query=search_query,
                    hobby=ingest_hobby,
                    item_type=item_type,
                )
                for key in totals:
                    totals[key] += result[key]
        else:
            totals = await _ingest_results(
                listing_results,
                search_query=args.query,
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
