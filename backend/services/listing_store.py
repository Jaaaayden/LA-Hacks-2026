import re
from datetime import datetime, timezone
from typing import Any

from backend.kitscout.db import listings
from backend.kitscout.schemas import Listing, Location

_OFFERUP_ID_RE = re.compile(r"/item/(?:detail/)?([^/?#]+)")


def parse_platform_id(url: str) -> str | None:
    """Extract listing ID from an OfferUp URL or id-like string."""
    if not url:
        return None
    m = _OFFERUP_ID_RE.search(url)
    if m:
        return m.group(1)
    cleaned = str(url).strip()
    if cleaned and "/" not in cleaned and " " not in cleaned:
        return cleaned
    return None


def parse_location(raw: str | dict[str, Any] | None) -> Location:
    if not raw:
        return Location()
    if isinstance(raw, dict):
        name = raw.get("name") or raw.get("locationName") or raw.get("raw")
        return Location(
            lat=_float_or_none(raw.get("latitude") or raw.get("lat")),
            lng=_float_or_none(raw.get("longitude") or raw.get("lng")),
            raw=str(name) if name else None,
        )
    parts = [p.strip() for p in raw.split(",", 1)]
    if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
        return Location(city=parts[0] or None, state=parts[1].upper(), raw=raw)
    return Location(city=parts[0] or None, raw=raw)


def normalize_condition(value: Any) -> str | None:
    text = str(value or "").lower()
    if not text:
        return None
    if "new" in text and "like" not in text:
        return "new"
    if "like new" in text or "open box" in text:
        return "like_new"
    if "fair" in text:
        return "fair"
    if "poor" in text or "damaged" in text or "for parts" in text:
        return "poor"
    if "good" in text or "used" in text or "normal wear" in text:
        return "good"
    return None


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _str_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def _price_or_zero(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("amount", "value", "price"):
            nested = value.get(key)
            if nested is not None:
                return _price_or_zero(nested)
        return 0.0
    text = str(value).strip()
    if not text:
        return 0.0
    lowered = text.lower()
    if lowered == "free":
        return 0.0
    numeric = re.sub(r"[^0-9.]", "", text)
    if not numeric:
        return 0.0
    try:
        return float(numeric)
    except (TypeError, ValueError):
        return 0.0


def to_listing(
    scraped: dict,
    *,
    search_query: str,
    hobby: str | None = None,
    item_type: str | None = None,
    query_id: str | None = None,
    list_id: str | None = None,
    item_id: str | None = None,
    scraped_at: datetime | None = None,
    source: str | None = None,
) -> Listing | None:
    raw_url = str(scraped.get("url") or "").strip()
    raw_platform_id = (
        scraped.get("platform_id")
        or scraped.get("listing_id")
        or scraped.get("listingId")
        or scraped.get("id")
    )
    platform_id = (
        str(raw_platform_id).strip()
        if raw_platform_id is not None and str(raw_platform_id).strip()
        else parse_platform_id(raw_url)
    )
    if not platform_id:
        return None
    url = raw_url or f"https://offerup.com/item/detail/{platform_id}"

    image_url = scraped.get("imageUrl") or scraped.get("image_url")
    if image_url and not str(image_url).startswith("http"):
        image_url = None
    image_path = scraped.get("image_path") or scraped.get("imagePath")
    location = scraped.get("location_detail") or scraped.get("location")
    condition_code = scraped.get("condition_code")

    try:
        return Listing(
            platform_id=platform_id,
            source=source or "offerup",
            url=url,
            title=scraped.get("title") or "",
            price_usd=_price_or_zero(scraped.get("price")),
            hobby=hobby or "unknown",
            item_type=item_type or "unknown",
            query_id=query_id,
            list_id=list_id,
            item_id=item_id,
            search_query=search_query,
            location=parse_location(location),
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
    item_type: str | None = None,
    query_id: str | None = None,
    list_id: str | None = None,
    item_id: str | None = None,
    scraped_at: datetime | None = None,
    source: str | None = None,
) -> dict[str, int]:
    counts = {"inserted": 0, "matched": 0, "skipped": 0}
    for raw in scraped:
        listing = to_listing(
            raw,
            search_query=search_query,
            hobby=hobby,
            item_type=item_type,
            query_id=query_id,
            list_id=list_id,
            item_id=item_id,
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
