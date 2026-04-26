from datetime import datetime, timezone

from backend.services.listing_store import (
    parse_platform_id,
    parse_location,
    to_listing,
)
from backend.kitscout.schemas import Listing, Location


def test_parse_platform_id_offerup_happy() -> None:
    assert (
        parse_platform_id("https://offerup.com/item/detail/987654321")
        == "987654321"
    )


def test_parse_platform_id_offerup_with_trailing_slash() -> None:
    assert (
        parse_platform_id("https://offerup.com/item/detail/55555/")
        == "55555"
    )


def test_parse_platform_id_no_match() -> None:
    assert parse_platform_id("https://example.com/listing/123") is None
    assert parse_platform_id("") is None


# ── parse_location ───────────────────────────────────────────
def test_parse_location_city_state() -> None:
    loc = parse_location("Pasco, WA")
    assert loc.city == "Pasco"
    assert loc.state == "WA"
    assert loc.raw == "Pasco, WA"


def test_parse_location_uppercases_state() -> None:
    loc = parse_location("Bend, or")
    assert loc.state == "OR"


def test_parse_location_city_only() -> None:
    loc = parse_location("Los Angeles")
    assert loc.city == "Los Angeles"
    assert loc.state is None


def test_parse_location_empty() -> None:
    loc = parse_location("")
    assert loc == Location()
    loc2 = parse_location(None)
    assert loc2 == Location()


def test_parse_location_long_state_token_stays_in_city() -> None:
    # "Selah, Washington" — state is full word, not 2 letters → keep as raw
    loc = parse_location("Selah, Washington")
    assert loc.city == "Selah"
    assert loc.state is None
    assert loc.raw == "Selah, Washington"


# ── to_listing ───────────────────────────────────────────────
_NOW = datetime.now(timezone.utc)


def test_to_listing_happy() -> None:
    raw = {
        "title": "Burton Custom Snowboard 158cm",
        "price": 180,
        "location": "Los Angeles, CA",
        "url": "https://offerup.com/item/detail/2226543014757869",
        "imageUrl": "https://images.offerup.com/img.jpg",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="snowboard",
        scraped_at=_NOW,
    )
    assert isinstance(listing, Listing)
    assert listing.platform_id == "2226543014757869"
    assert listing.source == "offerup"
    assert listing.price_usd == 180.0
    assert listing.hobby == "snowboarding"
    assert listing.item_type == "unknown"
    assert listing.location.city == "Los Angeles"
    assert listing.location.state == "CA"
    assert str(listing.image_url) == "https://images.offerup.com/img.jpg"
    assert listing.raw == raw  # original payload preserved


def test_to_listing_offerup() -> None:
    raw = {
        "title": "K2 Standard Snowboard 152cm",
        "price": 100,
        "location": "Pasadena, CA",
        "url": "https://offerup.com/item/detail/987654321",
        "image_url": "https://images.offerup.com/img.jpg",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="snowboard",
        scraped_at=_NOW,
    )
    assert isinstance(listing, Listing)
    assert listing.platform_id == "987654321"
    assert listing.source == "offerup"
    assert listing.price_usd == 100.0


def test_to_listing_accepts_numeric_offerup_condition_code() -> None:
    raw = {
        "title": "Burton Snowboard",
        "price": 100,
        "location_detail": {
            "name": "Huntington Park, CA",
            "latitude": "33.985",
            "longitude": "-118.207",
        },
        "condition_code": 40,
        "url": "https://offerup.com/item/detail/e9f3b6d8-05cb-310a-a4c5-6411561487b0",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="snowboard",
        scraped_at=_NOW,
    )
    assert listing is not None
    assert listing.platform_id == "e9f3b6d8-05cb-310a-a4c5-6411561487b0"
    assert listing.condition is None
    assert listing.condition_code == "40"
    assert listing.location.raw == "Huntington Park, CA"


def test_to_listing_drops_garbage_image_url() -> None:
    raw = {
        "title": "Snowboard",
        "price": 30,
        "location": "Kennewick, WA",
        "url": "https://offerup.com/item/detail/2226543014757869",
        "imageUrl": "1-25",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="snowboard",
        scraped_at=_NOW,
    )
    assert listing is not None
    assert listing.image_url is None


def test_to_listing_returns_none_on_missing_url() -> None:
    raw = {"title": "no url here", "price": 10}
    assert to_listing(raw, hobby="snowboarding", search_query="", scraped_at=_NOW) is None


def test_to_listing_returns_none_on_unparseable_platform_id() -> None:
    raw = {
        "title": "x",
        "price": 1,
        "url": "https://example.com/listing/abc",
    }
    assert to_listing(raw, hobby="snowboarding", search_query="", scraped_at=_NOW) is None


def test_to_listing_zero_price_is_valid() -> None:
    # Scraper writes 0 for "free" listings; should still be a valid Listing.
    raw = {
        "title": "Free snowboard",
        "price": 0,
        "location": "LA",
        "url": "https://offerup.com/item/detail/999",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="snowboard",
        scraped_at=_NOW,
    )
    assert listing is not None
    assert listing.price_usd == 0.0


def test_to_listing_keeps_shopping_list_context() -> None:
    raw = {
        "title": "Burton Moto Snowboard Boots, size 10",
        "price": 45,
        "location": "Long Beach, CA",
        "url": "https://offerup.com/item/detail/12345",
    }
    listing = to_listing(
        raw,
        hobby="snowboarding",
        search_query="size 10 snowboard boots",
        item_type="boots",
        query_id="query-1",
        list_id="list-1",
        item_id="item-1",
        scraped_at=_NOW,
    )
    assert listing is not None
    assert listing.item_type == "boots"
    assert listing.query_id == "query-1"
    assert listing.list_id == "list-1"
    assert listing.item_id == "item-1"
    assert listing.search_query == "size 10 snowboard boots"
