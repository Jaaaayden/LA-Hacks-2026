import asyncio
import os
import uuid
from datetime import datetime, timezone

import pytest
from dotenv import load_dotenv
from pymongo.errors import DuplicateKeyError

from backend.kitscout.schemas import (
    Listing,
    Location,
    Query,
    ShoppingList,
    ShoppingListAttribute,
    ShoppingListItem,
    ShoppingListValue,
)

load_dotenv()

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro) -> None:
    _LOOP.run_until_complete(coro)


def test_listing_schema_defaults() -> None:
    listing = Listing(
        platform_id="abc",
        url="https://offerup.com/item/detail/abc/",
        title="Test board",
        price_usd=100.0,
        hobby="snowboarding",
        item_type="board",
        scraped_at=datetime.now(timezone.utc),
    )
    assert listing.currency == "USD"
    assert listing.condition is None
    assert listing.location == Location()
    assert listing.raw == {}
    assert listing.source == "offerup"
    assert listing.list_id is None
    assert listing.item_id is None


def test_query_schema() -> None:
    now = datetime.now(timezone.utc)
    q = Query(
        raw_messages=["i want to snowboard"],
        parsed_intent={"hobby": "snowboarding", "budget_usd": None},
        followup_questions=["What is your budget?"],
        status="needs_followup",
        created_at=now,
        updated_at=now,
    )
    assert q.shopping_list_id is None
    assert q.parsed_intent["hobby"] == "snowboarding"
    assert q.raw_messages == ["i want to snowboard"]


def test_shopping_list_schema() -> None:
    shopping_list = ShoppingList(
        query_id="query-123",
        hobby="snowboarding",
        budget_usd=300.0,
        items=[
            ShoppingListItem(
                item_type="boots",
                search_query="size 10 snowboard boots",
                required=True,
                attributes=[
                    ShoppingListAttribute(
                        key="size",
                        value=[
                            ShoppingListValue(
                                value="10 US",
                                justification="User provided boot size.",
                            )
                        ],
                    )
                ],
                notes=None,
            )
        ],
        source_model="claude-sonnet-4-5",
        created_at=datetime.now(timezone.utc),
    )
    assert shopping_list.items[0].id
    assert shopping_list.items[0].attributes[0].value[0].value == "10 US"


pytestmark_mongo = pytest.mark.skipif(
    not os.getenv("MONGODB_URI"),
    reason="MONGODB_URI not set",
)


@pytestmark_mongo
@pytest.mark.mongo
def test_listing_round_trip() -> None:
    from backend.kitscout.db import listings
    from backend.kitscout.indexes import ensure_indexes

    platform_id = f"test-{uuid.uuid4()}"
    query_id = f"query-{uuid.uuid4()}"

    async def run() -> None:
        await ensure_indexes()
        try:
            doc = Listing(
                platform_id=platform_id,
                url=f"https://offerup.com/item/detail/{platform_id}/",
                title="Round-trip board",
                price_usd=123.45,
                hobby="snowboarding",
                item_type="board",
                condition="good",
                query_id=query_id,
                search_query="beginner snowboard",
                location=Location(city="Los Angeles", state="CA"),
                scraped_at=datetime.now(timezone.utc),
            ).model_dump()

            await listings.insert_one(doc)
            found = await listings.find_one({"platform_id": platform_id})

            assert found is not None
            assert found["title"] == "Round-trip board"
            assert found["price_usd"] == 123.45
            assert found["location"]["city"] == "Los Angeles"
            assert found["currency"] == "USD"
            assert found["query_id"] == query_id
        finally:
            await listings.delete_many({"platform_id": platform_id})

    _run(run())


@pytestmark_mongo
@pytest.mark.mongo
def test_unique_platform_id_index_rejects_duplicate() -> None:
    from backend.kitscout.db import listings
    from backend.kitscout.indexes import ensure_indexes

    platform_id = f"test-{uuid.uuid4()}"

    def make_doc() -> dict:
        return Listing(
            platform_id=platform_id,
            url=f"https://offerup.com/item/detail/{platform_id}/",
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
            await listings.delete_many({"platform_id": platform_id})

    _run(run())


@pytestmark_mongo
@pytest.mark.mongo
def test_shopping_list_round_trip() -> None:
    from backend.kitscout.db import shopping_lists

    query_id = f"test-query-{uuid.uuid4()}"

    async def run() -> None:
        try:
            doc = ShoppingList(
                query_id=query_id,
                hobby="snowboarding",
                budget_usd=250.0,
                items=[
                    ShoppingListItem(
                        item_type="helmet",
                        search_query="snowboard helmet",
                        required=True,
                        attributes=[],
                        notes=None,
                    )
                ],
                source_model="test-model",
                created_at=datetime.now(timezone.utc),
            ).model_dump()

            await shopping_lists.insert_one(doc)
            found = await shopping_lists.find_one({"query_id": query_id})

            assert found is not None
            assert found["hobby"] == "snowboarding"
            assert found["items"][0]["item_type"] == "helmet"
        finally:
            await shopping_lists.delete_many({"query_id": query_id})

    _run(run())
