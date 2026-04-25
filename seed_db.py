import asyncio
import json
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from kitscout.db import _db, item_comps, listings, offers, queries
from kitscout.indexes import ensure_indexes
from kitscout.schemas import ItemComp, Listing, Location, Offer, Query


def to_jsonable(doc):
    if isinstance(doc, dict):
        return {k: to_jsonable(v) for k, v in doc.items()}
    if isinstance(doc, list):
        return [to_jsonable(x) for x in doc]
    if isinstance(doc, ObjectId):
        return str(doc)
    if isinstance(doc, datetime):
        return doc.isoformat()
    return doc


_NOW = datetime.now(timezone.utc)


def _fb_url(fb_id: str) -> str:
    return f"https://facebook.com/marketplace/item/{fb_id}/"


SAMPLE_LISTINGS: list[Listing] = [
    # ── Snowboarding ────────────────────────────────────────────
    Listing(
        fb_id="2000000001",
        url=_fb_url("2000000001"),
        title="Burton Custom Snowboard 158cm",
        description="Used one season, minimal base scratches, edges sharp. No bindings.",
        price_usd=180.0,
        hobby="snowboarding",
        item_type="board",
        condition="good",
        skill_level_fit="intermediate",
        size="158cm",
        location=Location(city="Los Angeles", state="CA", raw="Los Angeles, CA"),
        image_url="https://example.com/img/snow-board-1.jpg",
        posted_at=_NOW - timedelta(days=2),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000002",
        url=_fb_url("2000000002"),
        title="K2 Standard Snowboard 152cm — beginner",
        description="Great first board, soft flex, used twice. All-mountain.",
        price_usd=120.0,
        hobby="snowboarding",
        item_type="board",
        condition="like_new",
        skill_level_fit="beginner",
        size="152cm",
        location=Location(city="Pasadena", state="CA", raw="Pasadena, CA"),
        image_url="https://example.com/img/snow-board-2.jpg",
        posted_at=_NOW - timedelta(days=5),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000003",
        url=_fb_url("2000000003"),
        title="Burton Moto Snowboard Boots, size 10",
        description="Comfortable beginner boot, BOA laces. Worn 4-5 times.",
        price_usd=45.0,
        hobby="snowboarding",
        item_type="boots",
        condition="good",
        skill_level_fit="beginner",
        size="10",
        location=Location(city="Long Beach", state="CA", raw="Long Beach, CA"),
        image_url="https://example.com/img/snow-boots-1.jpg",
        posted_at=_NOW - timedelta(days=1),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000004",
        url=_fb_url("2000000004"),
        title="Union Force bindings, medium",
        description="Reliable all-mountain bindings, great for any board.",
        price_usd=80.0,
        hobby="snowboarding",
        item_type="bindings",
        condition="good",
        skill_level_fit="intermediate",
        size="M",
        location=Location(city="Santa Monica", state="CA", raw="Santa Monica, CA"),
        image_url="https://example.com/img/snow-bindings-1.jpg",
        posted_at=_NOW - timedelta(days=7),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000005",
        url=_fb_url("2000000005"),
        title="Smith snowboard helmet, size M",
        description="MIPS-equipped, no cracks, used one season.",
        price_usd=35.0,
        hobby="snowboarding",
        item_type="helmet",
        condition="good",
        skill_level_fit="beginner",
        size="M",
        location=Location(city="Burbank", state="CA", raw="Burbank, CA"),
        image_url="https://example.com/img/snow-helmet-1.jpg",
        posted_at=_NOW - timedelta(days=3),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000006",
        url=_fb_url("2000000006"),
        title="Burton men's snowboard jacket, large",
        description="Waterproof shell, barely worn.",
        price_usd=60.0,
        hobby="snowboarding",
        item_type="jacket",
        condition="like_new",
        size="L",
        location=Location(city="Los Angeles", state="CA", raw="Los Angeles, CA"),
        image_url="https://example.com/img/snow-jacket-1.jpg",
        posted_at=_NOW - timedelta(days=10),
        scraped_at=_NOW,
    ),
    # ── Skateboarding ───────────────────────────────────────────
    Listing(
        fb_id="2000000101",
        url=_fb_url("2000000101"),
        title="Element complete skateboard 8.0",
        description="Complete deck, trucks, wheels. Some deck wear.",
        price_usd=55.0,
        hobby="skateboarding",
        item_type="complete",
        condition="good",
        skill_level_fit="beginner",
        size="8.0in",
        location=Location(city="Los Angeles", state="CA", raw="Los Angeles, CA"),
        image_url="https://example.com/img/skate-complete-1.jpg",
        posted_at=_NOW - timedelta(days=4),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000102",
        url=_fb_url("2000000102"),
        title="Independent Stage 11 trucks, 144mm",
        description="Pair of trucks, lightly used.",
        price_usd=30.0,
        hobby="skateboarding",
        item_type="trucks",
        condition="good",
        size="144mm",
        location=Location(city="Inglewood", state="CA", raw="Inglewood, CA"),
        image_url="https://example.com/img/skate-trucks-1.jpg",
        posted_at=_NOW - timedelta(days=6),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000103",
        url=_fb_url("2000000103"),
        title="Triple 8 skate helmet, size L",
        description="Certified, no cracks.",
        price_usd=20.0,
        hobby="skateboarding",
        item_type="helmet",
        condition="good",
        skill_level_fit="beginner",
        size="L",
        location=Location(city="Culver City", state="CA", raw="Culver City, CA"),
        image_url="https://example.com/img/skate-helmet-1.jpg",
        posted_at=_NOW - timedelta(days=2),
        scraped_at=_NOW,
    ),
    # ── Photography ─────────────────────────────────────────────
    Listing(
        fb_id="2000000201",
        url=_fb_url("2000000201"),
        title="Canon EOS Rebel T7 DSLR body",
        description="Body only, 24MP, ~5k shutter count. Charger included.",
        price_usd=240.0,
        hobby="photography",
        item_type="camera_body",
        condition="like_new",
        skill_level_fit="beginner",
        location=Location(city="Los Angeles", state="CA", raw="Los Angeles, CA"),
        image_url="https://example.com/img/photo-body-1.jpg",
        posted_at=_NOW - timedelta(days=1),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000202",
        url=_fb_url("2000000202"),
        title="Canon EF 50mm f/1.8 STM lens",
        description="The 'nifty fifty'. Great low-light, no scratches.",
        price_usd=85.0,
        hobby="photography",
        item_type="lens",
        condition="good",
        skill_level_fit="beginner",
        location=Location(city="West Hollywood", state="CA", raw="West Hollywood, CA"),
        image_url="https://example.com/img/photo-lens-1.jpg",
        posted_at=_NOW - timedelta(days=3),
        scraped_at=_NOW,
    ),
    Listing(
        fb_id="2000000203",
        url=_fb_url("2000000203"),
        title="Manfrotto travel tripod",
        description="Compact, carbon fiber legs. Bag included.",
        price_usd=70.0,
        hobby="photography",
        item_type="tripod",
        condition="good",
        location=Location(city="Glendale", state="CA", raw="Glendale, CA"),
        image_url="https://example.com/img/photo-tripod-1.jpg",
        posted_at=_NOW - timedelta(days=8),
        scraped_at=_NOW,
    ),
]


SAMPLE_COMPS: list[ItemComp] = [
    ItemComp(
        hobby="snowboarding",
        item_type="board",
        model="Burton Custom 158",
        median_price_usd=195.0,
        p25_usd=160.0,
        p75_usd=240.0,
        samples=14,
        updated_at=_NOW,
    ),
    ItemComp(
        hobby="snowboarding",
        item_type="boots",
        median_price_usd=55.0,
        p25_usd=35.0,
        p75_usd=80.0,
        samples=22,
        updated_at=_NOW,
    ),
    ItemComp(
        hobby="snowboarding",
        item_type="bindings",
        median_price_usd=90.0,
        p25_usd=60.0,
        p75_usd=120.0,
        samples=18,
        updated_at=_NOW,
    ),
    ItemComp(
        hobby="skateboarding",
        item_type="complete",
        median_price_usd=65.0,
        p25_usd=45.0,
        p75_usd=90.0,
        samples=27,
        updated_at=_NOW,
    ),
    ItemComp(
        hobby="photography",
        item_type="camera_body",
        model="Canon Rebel T7",
        median_price_usd=275.0,
        p25_usd=220.0,
        p75_usd=330.0,
        samples=11,
        updated_at=_NOW,
    ),
    ItemComp(
        hobby="photography",
        item_type="lens",
        model="Canon EF 50mm f/1.8",
        median_price_usd=95.0,
        p25_usd=75.0,
        p75_usd=115.0,
        samples=19,
        updated_at=_NOW,
    ),
]


SAMPLE_QUERIES: list[dict] = [
    {
        "raw_query": "I want to get into snowboarding, budget $300, in LA",
        "parsed_intent": {
            "hobby": "snowboarding",
            "budget_usd": 300.0,
            "location": "Los Angeles",
            "skill_level": "beginner",
            "user_details": {"age": None, "occupation": None, "constraints": None},
            "raw_query": "I want to get into snowboarding, budget $300, in LA",
        },
        "parsed_at": _NOW - timedelta(minutes=10),
    },
    {
        "raw_query": "want to start photography, $400, beginner",
        "parsed_intent": {
            "hobby": "photography",
            "budget_usd": 400.0,
            "location": None,
            "skill_level": "beginner",
            "user_details": {"age": None, "occupation": None, "constraints": None},
            "raw_query": "want to start photography, $400, beginner",
        },
        "parsed_at": _NOW - timedelta(minutes=2),
    },
]


async def main() -> None:
    await listings.delete_many({})
    await item_comps.delete_many({})
    await offers.delete_many({})
    await queries.delete_many({})

    await ensure_indexes()

    listings_result = await listings.insert_many(
        [l.model_dump() for l in SAMPLE_LISTINGS]
    )
    comps_result = await item_comps.insert_many(
        [c.model_dump() for c in SAMPLE_COMPS]
    )
    queries_result = await queries.insert_many(SAMPLE_QUERIES)

    # Build a sample Offer that ties query #0 to a beginner snowboard kit.
    # Match by fb_id so this is robust even if insert order shifts.
    fb_ids_in_kit = ["2000000002", "2000000003", "2000000005"]  # board, boots, helmet
    kit_listings = await listings.find(
        {"fb_id": {"$in": fb_ids_in_kit}}
    ).to_list(length=None)
    kit_listing_ids = [str(d["_id"]) for d in kit_listings]
    kit_total = sum(d["price_usd"] for d in kit_listings)

    offer = Offer(
        query_text=SAMPLE_QUERIES[0]["raw_query"],
        parsed_intent=SAMPLE_QUERIES[0]["parsed_intent"],
        listing_ids=kit_listing_ids,
        total_price_usd=kit_total,
        rationale=(
            "Beginner-friendly K2 board, comfortable Burton boots, and a Smith helmet — "
            f"total ${kit_total:.0f}, well under the $300 budget."
        ),
        created_at=_NOW,
    )
    offer_result = await offers.insert_one(offer.model_dump())

    # Link the query back to its offer.
    await queries.update_one(
        {"raw_query": SAMPLE_QUERIES[0]["raw_query"]},
        {"$set": {"offer_id": str(offer_result.inserted_id)}},
    )

    print(
        f"inserted: {len(listings_result.inserted_ids)} listings, "
        f"{len(comps_result.inserted_ids)} item_comps, "
        f"{len(queries_result.inserted_ids)} queries, "
        f"1 offer"
    )

    print()
    for name in await _db.list_collection_names():
        count = await _db[name].count_documents({})
        print(f"--- {name} ({count} docs) ---")
        async for doc in _db[name].find():
            print(json.dumps(to_jsonable(doc), indent=2))
        print()


if __name__ == "__main__":
    asyncio.run(main())
