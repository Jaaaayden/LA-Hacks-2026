import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId

from backend.kitscout.db import listings, queries, shopping_lists
from backend.kitscout.indexes import ensure_indexes
from backend.kitscout.schemas import (
    Listing,
    Location,
    Query,
    ShoppingList,
    ShoppingListItem,
)


def to_jsonable(doc: Any) -> Any:
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


async def main() -> None:
    await listings.delete_many({})
    await shopping_lists.delete_many({})
    await queries.delete_many({})
    await ensure_indexes()

    query = Query(
        raw_messages=[
            "I want to get into snowboarding, budget $300, in Los Angeles."
        ],
        parsed_intent={
            "hobby": "snowboarding",
            "budget_usd": 300,
            "location": "Los Angeles, CA",
            "skill_level": "beginner",
            "age": None,
            "misc": None,
            "other": [
                {"key": "boot_size", "label": "Boot size", "value": "10"},
                {
                    "key": "riding_style",
                    "label": "Riding style",
                    "value": "all-mountain",
                },
            ],
            "raw_query": [
                "I want to get into snowboarding, budget $300, in Los Angeles."
            ],
        },
        followup_questions=[],
        status="shopping_list_created",
        created_at=_NOW,
        updated_at=_NOW,
    )
    query_result = await queries.insert_one(query.model_dump())
    query_id = str(query_result.inserted_id)

    shopping_list = ShoppingList(
        query_id=query_id,
        hobby="snowboarding",
        budget_usd=300,
        items=[
            ShoppingListItem(
                item_type="snowboard",
                search_query="beginner all-mountain snowboard",
                budget_usd=140,
                required=True,
                attributes=[],
                notes="Beginner-friendly all-mountain board.",
            ),
            ShoppingListItem(
                item_type="boots",
                search_query="size 10 snowboard boots",
                budget_usd=70,
                required=True,
                attributes=[],
                notes=None,
            ),
            ShoppingListItem(
                item_type="helmet",
                search_query="snowboard helmet",
                budget_usd=40,
                required=True,
                attributes=[],
                notes="Safety gear should be bought only if it is in good condition.",
            ),
        ],
        source_model="seed",
        created_at=_NOW,
    )
    shopping_result = await shopping_lists.insert_one(shopping_list.model_dump())
    shopping_list_id = str(shopping_result.inserted_id)

    await queries.update_one(
        {"_id": query_result.inserted_id},
        {"$set": {"shopping_list_id": shopping_list_id}},
    )

    sample_listings = [
        Listing(
            platform_id="2000000001",
            url="https://facebook.com/marketplace/item/2000000001/",
            title="K2 Standard Snowboard 152cm beginner",
            price_usd=120,
            hobby="snowboarding",
            item_type="snowboard",
            query_id=query_id,
            shopping_list_id=shopping_list_id,
            shopping_list_item_type="snowboard",
            search_query="beginner all-mountain snowboard",
            location=Location(city="Pasadena", state="CA", raw="Pasadena, CA"),
            scraped_at=_NOW,
        ),
        Listing(
            platform_id="2000000002",
            url="https://facebook.com/marketplace/item/2000000002/",
            title="Burton Moto Snowboard Boots size 10",
            price_usd=45,
            hobby="snowboarding",
            item_type="boots",
            query_id=query_id,
            shopping_list_id=shopping_list_id,
            shopping_list_item_type="boots",
            search_query="size 10 snowboard boots",
            location=Location(city="Long Beach", state="CA", raw="Long Beach, CA"),
            scraped_at=_NOW,
        ),
    ]
    await listings.insert_many([listing.model_dump() for listing in sample_listings])

    print("inserted: 1 query, 1 shopping_list, 2 listings")
    for name, collection in {
        "queries": queries,
        "shopping_lists": shopping_lists,
        "listings": listings,
    }.items():
        docs = await collection.find().to_list(length=None)
        print(f"\n--- {name} ({len(docs)} docs) ---")
        for doc in docs:
            print(json.dumps(to_jsonable(doc), indent=2))


if __name__ == "__main__":
    asyncio.run(main())