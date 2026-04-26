import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from html import unescape
from typing import Any

import httpx
from dotenv import load_dotenv

load_dotenv()

OFFERUP_GRAPHQL_URL = "https://offerup.com/api/graphql"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:150.0) "
    "Gecko/20100101 Firefox/150.0"
)
DEFAULT_EXPERIMENT_ID = "experimentmodel24"
DEFAULT_LIMIT = 50
DEFAULT_MIN_PRICE = 2

_ZIP_RE = re.compile(r"^\d{5}(?:-\d{4})?$")
_LAT_LON_RE = re.compile(
    r"^\s*(?P<lat>-?\d+(?:\.\d+)?)\s*,\s*(?P<lon>-?\d+(?:\.\d+)?)\s*$"
)
_OFFERUP_DETAIL_RE = re.compile(r"/item/detail/([^/?#]+)")
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(?P<json>.*?)</script>',
    re.DOTALL,
)


@dataclass(frozen=True)
class OfferUpLocation:
    city: str | None
    state: str | None
    zip_code: str | None
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        parts = [p for p in (self.city, self.state) if p]
        return ", ".join(parts) or self.zip_code or f"{self.latitude},{self.longitude}"


DEFAULT_LOCATION = OfferUpLocation(
    city="Los Angeles",
    state="CA",
    zip_code="90064",
    latitude=34.0318,
    longitude=-118.4252,
)

_KNOWN_LOCATIONS: dict[str, OfferUpLocation] = {
    "la": DEFAULT_LOCATION,
    "los angeles": DEFAULT_LOCATION,
    "los angeles, ca": DEFAULT_LOCATION,
    "irvine": OfferUpLocation("Irvine", "CA", "92604", 33.7069329, -117.7841771),
    "irvine, ca": OfferUpLocation("Irvine", "CA", "92604", 33.7069329, -117.7841771),
}

GET_MODULAR_FEED_QUERY = """
query GetModularFeed($searchParams: [SearchParam], $debug: Boolean = false) {
  modularFeed(params: $searchParams, debug: $debug) {
    looseTiles {
      __typename
      ... on ModularFeedTileListing {
        listing {
          ...modularListing
        }
      }
      ... on ModularFeedTileSellerAd {
        listing {
          ...modularListing
        }
      }
    }
    modules {
      __typename
      ... on ModularFeedModuleGrid {
        grid {
          tiles {
            __typename
            ... on ModularFeedTileListing {
              listing {
                ...modularListing
              }
            }
            ... on ModularFeedTileSellerAd {
              listing {
                ...modularListing
              }
            }
          }
        }
      }
    }
    pageCursor
    query {
      appliedQuery
      originalQuery
      suggestedQuery
    }
  }
}

fragment modularListing on ModularFeedListing {
  listingId
  conditionText
  flags
  image {
    height
    url
    width
  }
  isFirmPrice
  locationName
  price
  title
  vehicleMiles
}
"""

GEOCODE_LOCATION_QUERY = """
query GeocodeLocation($input: GeocodeLocationInput!) {
  geocodeLocation(input: $input) {
    location {
      city
      latitude
      longitude
      state
      zipCode
    }
  }
}
"""


def _device_id() -> str:
    return os.environ.get("OFFERUP_DEVICE_ID") or f"web-{uuid.uuid4().hex}"


def _headers(operation_name: str, *, referer_query: str | None = None) -> dict[str, str]:
    user_agent = os.environ.get("OFFERUP_USER_AGENT") or DEFAULT_USER_AGENT
    device_id = _device_id()
    user_context = os.environ.get("OFFERUP_USER_CONTEXT") or json.dumps(
        {
            "device_id": device_id,
            "user_agent": user_agent,
            "device_platform": "web",
        },
        separators=(",", ":"),
    )

    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "content-type": "application/json",
        "Origin": "https://offerup.com",
        "Referer": f"https://offerup.com/search?q={referer_query or ''}",
        "ou-experiment-data": json.dumps(
            {"datamodel_id": DEFAULT_EXPERIMENT_ID}, separators=(",", ":")
        ),
        "x-ou-d-token": os.environ.get("OFFERUP_D_TOKEN") or device_id,
        "ou-browser-user-agent": user_agent,
        "x-ou-usercontext": user_context,
        "ou-session-id": os.environ.get("OFFERUP_SESSION_ID")
        or f"{device_id}@{int(time.time() * 1000)}",
        "x-ou-operation-name": operation_name,
        "x-request-id": str(uuid.uuid4()),
    }

    userdata = os.environ.get("OFFERUP_USERDATA")
    if userdata:
        headers["userdata"] = userdata

    cookie = os.environ.get("OFFERUP_COOKIE")
    if cookie:
        headers["Cookie"] = cookie

    return headers


def _document_headers(referer: str = "https://offerup.com/") -> dict[str, str]:
    user_agent = os.environ.get("OFFERUP_USER_AGENT") or DEFAULT_USER_AGENT
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    }
    cookie = os.environ.get("OFFERUP_COOKIE")
    if cookie:
        headers["Cookie"] = cookie
    return headers


_RATE_LIMIT_BACKOFFS_S = (5.0, 15.0, 45.0)


async def _sleep_for_retry(response: httpx.Response, attempt: int) -> None:
    """Honor Retry-After when OfferUp sends one; otherwise exponential backoff.

    OfferUp's edge sometimes returns Retry-After in seconds, sometimes not at
    all. The fallback schedule (5s, 15s, 45s) keeps total wait under the
    bureau's 150s scrape timeout in `_run_live_scrape`.
    """
    retry_after = response.headers.get("retry-after")
    delay = _RATE_LIMIT_BACKOFFS_S[min(attempt, len(_RATE_LIMIT_BACKOFFS_S) - 1)]
    if retry_after:
        try:
            delay = max(delay, float(retry_after))
        except ValueError:
            pass
    await asyncio.sleep(delay)


async def _post_graphql(
    operation_name: str,
    variables: dict[str, Any],
    query: str,
    *,
    referer_query: str | None = None,
) -> dict[str, Any]:
    payload = {
        "operationName": operation_name,
        "variables": variables,
        "query": query,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(len(_RATE_LIMIT_BACKOFFS_S) + 1):
            response = await client.post(
                OFFERUP_GRAPHQL_URL,
                headers=_headers(operation_name, referer_query=referer_query),
                json=payload,
            )
            if response.status_code == 429 and attempt < len(_RATE_LIMIT_BACKOFFS_S):
                await _sleep_for_retry(response, attempt)
                continue
            response.raise_for_status()
            data = response.json()
            break
    if data.get("errors"):
        raise RuntimeError(f"OfferUp GraphQL error: {data['errors']}")
    return data


def _parse_price(raw: Any) -> float:
    if raw is None:
        return 0.0
    if isinstance(raw, int | float):
        return float(raw)
    text = str(raw).replace(",", "")
    if text.lower().strip() == "free":
        return 0.0
    match = re.search(r"\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else 0.0


def _location_from_graphql(raw: dict[str, Any]) -> OfferUpLocation:
    return OfferUpLocation(
        city=raw.get("city"),
        state=raw.get("state"),
        zip_code=raw.get("zipCode"),
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
    )


async def resolve_location(location: str | None) -> OfferUpLocation:
    if not location:
        return DEFAULT_LOCATION

    location = location.strip()
    lat_lon_match = _LAT_LON_RE.match(location)
    if lat_lon_match:
        return OfferUpLocation(
            city=None,
            state=None,
            zip_code=None,
            latitude=float(lat_lon_match.group("lat")),
            longitude=float(lat_lon_match.group("lon")),
        )

    known = _KNOWN_LOCATIONS.get(location.lower())
    if known:
        return known

    if not _ZIP_RE.match(location):
        raise ValueError(
            "OfferUp location must be a ZIP code, 'lat,lon', or a known city "
            f"({', '.join(sorted(_KNOWN_LOCATIONS))}). Got: {location!r}"
        )

    data = await _post_graphql(
        "GeocodeLocation",
        {"input": {"zipcode": location[:5]}},
        GEOCODE_LOCATION_QUERY,
        referer_query="",
    )
    raw_location = (
        data.get("data", {})
        .get("geocodeLocation", {})
        .get("location")
    )
    if not raw_location:
        raise ValueError(f"OfferUp could not geocode ZIP code: {location}")
    return _location_from_graphql(raw_location)


def _search_params(
    *,
    query: str,
    location: OfferUpLocation,
    limit: int,
    search_session_id: str,
    page_cursor: str | None,
    min_price: int | None = None,
) -> list[dict[str, str]]:
    params = [
        {"key": "q", "value": query},
        {"key": "platform", "value": "web"},
        {"key": "lon", "value": str(location.longitude)},
        {"key": "lat", "value": str(location.latitude)},
        {"key": "experiment_id", "value": DEFAULT_EXPERIMENT_ID},
        {"key": "limit", "value": str(limit)},
        {"key": "searchSessionId", "value": search_session_id},
    ]
    if min_price is not None:
        params.append({"key": "price_min", "value": str(min_price)})
    if page_cursor:
        params.append({"key": "page_cursor", "value": page_cursor})
    return params


def _iter_raw_listings(modular_feed: dict[str, Any]) -> list[dict[str, Any]]:
    listings: list[dict[str, Any]] = []

    for tile in modular_feed.get("looseTiles") or []:
        listing = tile.get("listing")
        if listing:
            listings.append(listing)

    for module in modular_feed.get("modules") or []:
        grid = module.get("grid") or {}
        for tile in grid.get("tiles") or []:
            listing = tile.get("listing")
            if listing:
                listings.append(listing)

    return listings


def _normalize_listing(raw: dict[str, Any]) -> dict[str, Any] | None:
    listing_id = raw.get("listingId")
    if not listing_id:
        return None

    image = raw.get("image") or {}
    price = _parse_price(raw.get("price"))
    return {
        "title": raw.get("title") or "",
        "price": price,
        "location": raw.get("locationName") or "",
        "url": f"https://offerup.com/item/detail/{listing_id}",
        "image_url": image.get("url"),
        "condition": raw.get("conditionText"),
        "raw": raw,
    }


def _listing_id_from_item(item: str | dict[str, Any]) -> str:
    if isinstance(item, dict):
        for key in ("listingId", "listing_id", "platform_id", "id"):
            value = item.get(key)
            if value:
                return str(value)
        url = item.get("url")
        if url:
            return _listing_id_from_item(str(url))
        raise ValueError("OfferUp item dict does not include a listing id or url.")

    item = item.strip()
    match = _OFFERUP_DETAIL_RE.search(item)
    if match:
        return match.group(1)
    if item:
        return item
    raise ValueError("OfferUp item id/url cannot be empty.")


def _extract_next_data(html: str) -> dict[str, Any]:
    match = _NEXT_DATA_RE.search(html)
    if not match:
        raise ValueError("OfferUp detail page did not include __NEXT_DATA__.")
    return json.loads(unescape(match.group("json")))


def _ref(state: dict[str, Any], ref_obj: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ref_obj:
        return None
    ref = ref_obj.get("__ref")
    if not ref:
        return None
    value = state.get(ref)
    return value if isinstance(value, dict) else None


def _find_listing_detail(
    state: dict[str, Any], listing_id: str
) -> dict[str, Any]:
    root_query = state.get("ROOT_QUERY") or {}
    expected_key = f'listing({{"listingId":"{listing_id}"}})'
    listing = root_query.get(expected_key)
    if isinstance(listing, dict):
        return listing

    for key, value in root_query.items():
        if (
            key.startswith("listing(")
            and listing_id in key
            and isinstance(value, dict)
        ):
            return value

    raise ValueError(f"OfferUp listing detail not found in page data: {listing_id}")


def _image_url(image: dict[str, Any] | None) -> str | None:
    if not image:
        return None
    url = image.get("url")
    return str(url) if url else None


def _normalize_photos(raw_photos: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    photos: list[dict[str, Any]] = []
    for photo in raw_photos or []:
        photos.append(
            {
                "uuid": photo.get("uuid"),
                "detail_url": _image_url(photo.get("detail")),
                "full_url": _image_url(photo.get("detailFull")),
                "square_url": _image_url(photo.get("detailSquare")),
                "list_url": _image_url(photo.get("list")),
            }
        )
    return photos


def _normalize_seller(owner: dict[str, Any] | None) -> dict[str, Any] | None:
    if not owner:
        return None
    profile = owner.get("profile") or {}
    avatars = profile.get("avatars") or {}
    rating = profile.get("ratingSummary") or {}
    return {
        "id": owner.get("id"),
        "name": profile.get("name"),
        "avatar_url": avatars.get("squareImage"),
        "public_location": profile.get("publicLocationName"),
        "date_joined": profile.get("dateJoined"),
        "last_active": profile.get("lastActive"),
        "items_sold": profile.get("itemsSold"),
        "items_purchased": profile.get("itemsPurchased"),
        "response_time": profile.get("responseTime"),
        "rating_average": rating.get("average"),
        "rating_count": rating.get("count"),
        "is_truyou_verified": profile.get("isTruyouVerified"),
        "is_business_account": profile.get("isBusinessAccount"),
    }


def _normalize_category(category: dict[str, Any] | None) -> dict[str, Any] | None:
    if not category:
        return None
    category_v2 = category.get("categoryV2") or {}
    attributes = []
    for attr in category.get("categoryAttributeMap") or []:
        attributes.append(
            {
                "name": attr.get("attributeName"),
                "label": attr.get("attributeUILabel"),
                "value": attr.get("attributeValue") or [],
                "priority": attr.get("attributePriority"),
            }
        )
    return {
        "id": category_v2.get("id"),
        "name": category_v2.get("name"),
        "l1_name": category_v2.get("l1Name"),
        "l2_name": category_v2.get("l2Name"),
        "l3_name": category_v2.get("l3Name"),
        "attributes": attributes,
    }


def _normalize_listing_detail(
    listing: dict[str, Any],
    *,
    owner: dict[str, Any] | None,
    category: dict[str, Any] | None,
) -> dict[str, Any]:
    listing_id = str(listing.get("listingId") or "")
    location = listing.get("locationDetails") or {}
    distance = listing.get("distance") or {}
    fulfillment = listing.get("fulfillmentDetails") or {}
    photos = _normalize_photos(listing.get("photos"))
    image_url = next((p.get("list_url") or p.get("full_url") for p in photos), None)

    return {
        "listing_id": listing_id,
        "internal_id": listing.get("id"),
        "url": f"https://offerup.com/item/detail/{listing_id}",
        "title": listing.get("title") or listing.get("originalTitle") or "",
        "description": listing.get("description"),
        "price": _parse_price(listing.get("price") or listing.get("originalPrice")),
        "original_price": listing.get("originalPrice"),
        "condition_code": listing.get("condition"),
        "post_date": listing.get("postDate"),
        "state": listing.get("state"),
        "is_removed": listing.get("isRemoved"),
        "is_local": listing.get("isLocal"),
        "is_firm_on_price": listing.get("isFirmOnPrice"),
        "quantity": listing.get("quantity"),
        "location": {
            "name": location.get("locationName"),
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
        },
        "distance": {
            "value": distance.get("value"),
            "unit": distance.get("unit"),
        },
        "fulfillment": {
            "local_pickup_enabled": fulfillment.get("localPickupEnabled"),
            "shipping_enabled": fulfillment.get("shippingEnabled"),
            "can_ship_to_buyer": fulfillment.get("canShipToBuyer"),
            "buy_it_now_enabled": fulfillment.get("buyItNowEnabled"),
            "seller_pays_shipping": fulfillment.get("sellerPaysShipping"),
            "shipping_price": fulfillment.get("shippingPrice"),
        },
        "image_url": image_url,
        "photos": photos,
        "seller": _normalize_seller(owner),
        "category": _normalize_category(category),
    }


async def search_offerup_graphql(
    query: str,
    *,
    min_price: int | None = DEFAULT_MIN_PRICE,
    max_price: int | None = None,
    max_results: int = 30,
    location: str | None = None,
    page_limit: int = DEFAULT_LIMIT,
    include_details: bool = True,
    detail_concurrency: int = 5,
) -> list[dict]:
    resolved_location = await resolve_location(location)
    search_session_id = str(uuid.uuid4())
    page_cursor: str | None = None
    listings: list[dict] = []
    seen_ids: set[str] = set()

    while len(listings) < max_results:
        variables = {
            "debug": False,
            "searchParams": _search_params(
                query=query,
                location=resolved_location,
                limit=page_limit,
                search_session_id=search_session_id,
                page_cursor=page_cursor,
                min_price=min_price,
            ),
        }
        data = await _post_graphql(
            "GetModularFeed",
            variables,
            GET_MODULAR_FEED_QUERY,
            referer_query=query,
        )
        modular_feed = data.get("data", {}).get("modularFeed") or {}

        for raw in _iter_raw_listings(modular_feed):
            listing_id = str(raw.get("listingId") or "")
            if not listing_id or listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)

            listing = _normalize_listing(raw)
            if listing is None:
                continue
            if min_price is not None and listing["price"] < min_price:
                continue
            if max_price is not None and listing["price"] > max_price:
                continue
            listings.append(listing)
            if len(listings) >= max_results:
                break

        next_cursor = modular_feed.get("pageCursor")
        if not next_cursor or next_cursor == page_cursor:
            break
        page_cursor = next_cursor

    if not include_details:
        return listings

    return await enrich_offerup_listings_with_details(
        listings,
        concurrency=detail_concurrency,
    )


def _merge_listing_detail(search_listing: dict, detail: dict[str, Any]) -> dict:
    merged = dict(search_listing)
    merged.pop("raw", None)

    merged.update(
        {
            "title": detail.get("title") or search_listing.get("title") or "",
            "price": detail.get("price", search_listing.get("price", 0.0)),
            "description": detail.get("description"),
            "condition_code": detail.get("condition_code"),
            "post_date": detail.get("post_date"),
            "state": detail.get("state"),
            "is_removed": detail.get("is_removed"),
            "is_local": detail.get("is_local"),
            "is_firm_on_price": detail.get("is_firm_on_price"),
            "quantity": detail.get("quantity"),
            "photos": detail.get("photos") or [],
            "seller": detail.get("seller"),
            "category": detail.get("category"),
            "fulfillment": detail.get("fulfillment"),
            "distance": detail.get("distance"),
            "location_detail": detail.get("location"),
        }
    )

    if detail.get("image_url"):
        merged["image_url"] = detail["image_url"]
    detail_location = detail.get("location") or {}
    if detail_location.get("name"):
        merged["location"] = detail_location["name"]

    return merged


async def enrich_offerup_listings_with_details(
    listings: list[dict],
    *,
    concurrency: int = 5,
) -> list[dict]:
    """Fetch embedded item-page details for each search listing."""
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def enrich_one(listing: dict) -> dict:
        async with semaphore:
            try:
                detail = await get_offerup_listing_detail(listing)
            except Exception as exc:
                enriched = dict(listing)
                enriched["detail_error"] = f"{type(exc).__name__}: {exc}"
                return enriched
            return _merge_listing_detail(listing, detail)

    return list(await asyncio.gather(*(enrich_one(listing) for listing in listings)))


async def get_offerup_listing_detail(item: str | dict[str, Any]) -> dict[str, Any]:
    """Fetch all available details for an OfferUp listing.

    `item` can be a listing ID, an OfferUp detail URL, or one of the dicts
    returned by `search_offerup_graphql()`.
    """
    listing_id = _listing_id_from_item(item)
    url = f"https://offerup.com/item/detail/{listing_id}"
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for attempt in range(len(_RATE_LIMIT_BACKOFFS_S) + 1):
            response = await client.get(url, headers=_document_headers())
            if response.status_code == 429 and attempt < len(_RATE_LIMIT_BACKOFFS_S):
                await _sleep_for_retry(response, attempt)
                continue
            response.raise_for_status()
            break

    next_data = _extract_next_data(response.text)
    state = (
        next_data.get("props", {})
        .get("pageProps", {})
        .get("initialApolloState")
        or {}
    )
    listing = _find_listing_detail(state, listing_id)
    owner = _ref(state, listing.get("owner"))
    category = _ref(state, listing.get("listingCategory"))
    return _normalize_listing_detail(listing, owner=owner, category=category)
