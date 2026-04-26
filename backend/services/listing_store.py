import re
from datetime import datetime, timezone

from backend.kitscout.db import listings
from backend.kitscout.schemas import Listing, Location

_OFFERUP_ID_RE = re.compile(r"/item/detail/(\d+)")

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


def parse_platform_id(url: str) -> str | None:
    """Extract the numeric item ID from an OfferUp listing URL."""
    if not url:
        return None
    m = _OFFERUP_ID_RE.search(url)
    if m:
        return m.group(1)
    return None


def parse_offerup_id(url: str) -> str | None:
    """Extract the numeric item ID from an OfferUp URL."""
    if not url:
        return None
    m = _OFFERUP_ID_RE.search(url)
    return m.group(1) if m else None


def _detect_source(url: str) -> str:
    """Infer the listing source from its URL."""
    if "offerup.com" in url:
        return "offerup"
    return "offerup"


def parse_location(raw: str | None) -> Location:
    if not raw:
        return Location()
    parts = [p.strip() for p in raw.split(",", 1)]
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        return Location(city=parts[0] or None, state=parts[1].upper(), raw=raw)
    return Location(city=parts[0] or None, raw=raw)


def infer_hobby(search_query: str) -> str:
    text = search_query.lower()
    for hobby, keywords in _HOBBY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return hobby
    return "unknown"


def classify_item_type(title: str, search_query: str, hobby: str) -> str:
    text = f"{title} {search_query}".lower()
    if hobby == "snowboarding":
        for keyword, item_type in _SNOWBOARDING_ITEMS:
            if keyword in text:
                return item_type
        return "board"
    return "unknown"


def to_listing(
    scraped: dict,
    *,
    search_query: str,
    hobby: str | None = None,
    shopping_list_item_type: str | None = None,
    query_id: str | None = None,
    shopping_list_id: str | None = None,
    scraped_at: datetime | None = None,
    source: str | None = None,
) -> Listing | None:
    url = scraped.get("url") or ""
    platform_id = parse_platform_id(url)
    if not platform_id:
        return None

    resolved_source = source or _detect_source(url)

    image_url = scraped.get("imageUrl") or scraped.get("image_url")
    if image_url and not str(image_url).startswith("http"):
        image_url = None
    image_path = scraped.get("image_path") or scraped.get("imagePath")

    resolved_hobby = hobby or infer_hobby(search_query)
    item_type = shopping_list_item_type or classify_item_type(
        scraped.get("title", ""),
        search_query,
        resolved_hobby,
    )

    try:
        return Listing(
            platform_id=platform_id,
            source=resolved_source,
            url=url,
            title=scraped.get("title") or "",
            price_usd=float(scraped.get("price") or 0),
            hobby=resolved_hobby,
            item_type=item_type,
            query_id=query_id,
            shopping_list_id=shopping_list_id,
            shopping_list_item_type=shopping_list_item_type,
            search_query=search_query,
            location=parse_location(scraped.get("location")),
            image_url=image_url,
            image_path=image_path,
            scraped_at=scraped_at or datetime.now(timezone.utc),
            raw=scraped,
        )
    except Exception:
        return None


async def upsert_scraped_listings(
    scraped: list[dict],
    *,
    search_query: str,
    hobby: str | None = None,
    shopping_list_item_type: str | None = None,
    query_id: str | None = None,
    shopping_list_id: str | None = None,
    scraped_at: datetime | None = None,
    source: str | None = None,
) -> dict[str, int]:
    counts = {"inserted": 0, "matched": 0, "skipped": 0}
    for raw in scraped:
        listing = to_listing(
            raw,
            search_query=search_query,
            hobby=hobby,
            shopping_list_item_type=shopping_list_item_type,
            query_id=query_id,
            shopping_list_id=shopping_list_id,
            scraped_at=scraped_at,
            source=source,
        )
        if listing is None:
            counts["skipped"] += 1
            continue

        result = await listings.update_one(
            {"platform_id": listing.platform_id, "source": listing.source},
            {"$set": listing.model_dump()},
            upsert=True,
        )
        if result.upserted_id is not None:
            counts["inserted"] += 1
        else:
            counts["matched"] += 1

    return counts
