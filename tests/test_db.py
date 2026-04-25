import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv
from pymongo.errors import DuplicateKeyError

from kitscout.schemas import ItemComp, Listing, Location, Offer, Query

load_dotenv()

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro) -> None:
    _LOOP.run_until_complete(coro)


def test_listing_schema_defaults() -> None:
    listing = Listing(
        fb_id="abc",
        url="https://facebook.com/marketplace/item/abc/",
        title="Test board",
        price_usd=100.0,
        hobby="snowboarding",
        item_type="board",
        scraped_at=datetime.now(timezone.utc),
    )
    assert listing.currency == "USD"
    assert listing.condition is None
    assert listing.skill_level_fit is None
    assert listing.location == Location()
    assert listing.raw == {}


def test_query_schema() -> None:
    q = Query(
        raw_query="i want to snowboard",
        parsed_intent={"hobby": "snowboarding", "budget_usd": None},
        parsed_at=datetime.now(timezone.utc),
    )
    assert q.offer_id is None
    assert q.parsed_intent["hobby"] == "snowboarding"


def test_offer_schema() -> None:
    offer = Offer(
        query_text="x",
        parsed_intent={},
        listing_ids=["6543210fedcba9876"],
        total_price_usd=275.0,
        created_at=datetime.now(timezone.utc),
    )
    assert offer.rationale is None
    assert len(offer.listing_ids) == 1


pytestmark_mongo = pytest.mark.skipif(
    not os.getenv("MONGODB_URI"),
    reason="MONGODB_URI not set",
)


@pytestmark_mongo
@pytest.mark.mongo
def test_listing_round_trip() -> None:
    from kitscout.db import listings
    from kitscout.indexes import ensure_indexes

    fb_id = f"test-{uuid.uuid4()}"

    async def run() -> None:
        await ensure_indexes()
        try:
            doc = Listing(
                fb_id=fb_id,
                url=f"https://facebook.com/marketplace/item/{fb_id}/",
                title="Round-trip board",
                price_usd=123.45,
                hobby="snowboarding",
                item_type="board",
                condition="good",
                location=Location(city="Los Angeles", state="CA"),
                scraped_at=datetime.now(timezone.utc),
            ).model_dump()

            await listings.insert_one(doc)
            found = await listings.find_one({"fb_id": fb_id})

            assert found is not None
            assert found["title"] == "Round-trip board"
            assert found["price_usd"] == 123.45
            assert found["location"]["city"] == "Los Angeles"
            assert found["currency"] == "USD"
        finally:
            await listings.delete_many({"fb_id": fb_id})

    _run(run())


@pytestmark_mongo
@pytest.mark.mongo
def test_unique_fb_id_index_rejects_duplicate() -> None:
    from kitscout.db import listings
    from kitscout.indexes import ensure_indexes

    fb_id = f"test-{uuid.uuid4()}"

    def make_doc() -> dict:
        return Listing(
            fb_id=fb_id,
            url=f"https://facebook.com/marketplace/item/{fb_id}/",
            title="Dup test",
            price_usd=10.0,
            hobby="snowboarding",
            item_type="board",
            scraped_at=datetime.now(timezone.utc),
        ).model_dump()

    async def run() -> None:
        await ensure_indexes()
        try:
            await listings.insert_one(make_doc())
            with pytest.raises(DuplicateKeyError):
                await listings.insert_one(make_doc())
        finally:
            await listings.delete_many({"fb_id": fb_id})

    _run(run())


@pytestmark_mongo
@pytest.mark.mongo
def test_item_comp_round_trip() -> None:
    from kitscout.db import item_comps

    model_name = f"test-comp-{uuid.uuid4()}"

    async def run() -> None:
        try:
            doc = ItemComp(
                hobby="snowboarding",
                item_type="board",
                model=model_name,
                median_price_usd=200.0,
                samples=5,
                updated_at=datetime.now(timezone.utc),
            ).model_dump()

            await item_comps.insert_one(doc)
            found = await item_comps.find_one({"model": model_name})

            assert found is not None
            assert found["median_price_usd"] == 200.0
            assert found["samples"] == 5
        finally:
            await item_comps.delete_many({"model": model_name})

    _run(run())
