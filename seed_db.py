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
                id="item-snowboard",
                item_type="snowboard",
                search_query="beginner all-mountain snowboard",
                budget_usd=140,
                required=True,
                attributes=[],
                notes="Beginner-friendly all-mountain board.",
            ),
            ShoppingListItem(
                id="item-boots",
                item_type="boots",
                search_query="size 10 snowboard boots",
                budget_usd=70,
                required=True,
                attributes=[],
                notes=None,
            ),
            ShoppingListItem(
                id="item-helmet",
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

    def _listing(
        platform_id: str,
        title: str,
        price: float,
        item_type: str,
        city: str,
        search_query: str | None = None,
    ) -> Listing:
        item_ids = {
            "snowboard": "item-snowboard",
            "boots": "item-boots",
            "helmet": "item-helmet",
        }
        return Listing(
            platform_id=platform_id,
            url=f"https://offerup.com/item/detail/{platform_id}/",
            title=title,
            price_usd=price,
            hobby="snowboarding",
            item_type=item_type,
            query_id=query_id,
            list_id=shopping_list_id,
            item_id=item_ids.get(item_type),
            search_query=search_query or item_type,
            location=Location(city=city, state="CA", raw=f"{city}, CA"),
            scraped_at=_NOW,
        )

    # Two listings per common kit item so the agent has a choice and Pricer
    # (Phase 4) has comps to score against.
    sample_listings = [
        _listing("2000000001", "K2 Standard Snowboard 152cm beginner", 120, "snowboard", "Pasadena", "beginner all-mountain snowboard"),
        _listing("2000000002", "Burton Custom 156 all-mountain", 180, "snowboard", "Santa Monica", "all-mountain snowboard"),

        _listing("2000000010", "Burton Moto Snowboard Boots size 9", 45, "boots", "Long Beach", "size 9 snowboard boots"),
        _listing("2000000011", "Salomon Faction boots size 10 like new", 80, "boots", "Burbank", "size 10 snowboard boots"),

        _listing("2000000020", "Burton Mission bindings medium", 55, "bindings", "Glendale", "all-mountain snowboard bindings"),
        _listing("2000000021", "Union Force bindings size L lightly used", 90, "bindings", "Culver City", "snowboard bindings large"),

        _listing("2000000030", "Smith Holt snowboard helmet medium", 35, "helmet", "Hollywood", "snowboard helmet medium"),
        _listing("2000000031", "Giro Ledge MIPS helmet large", 60, "helmet", "Westwood", "MIPS snowboard ski helmet"),

        _listing("2000000040", "Anon Helix 2.0 snowboard goggles", 40, "goggles", "Venice", "snowboard goggles low light"),
        _listing("2000000041", "Smith Squad XL goggles spare lens", 70, "goggles", "Silver Lake", "snowboard goggles two lens"),

        _listing("2000000050", "Burton AK Gore-Tex jacket size M", 130, "jacket", "Echo Park", "snowboard jacket waterproof"),
        _listing("2000000051", "686 Smarty 3-in-1 jacket size L", 95, "jacket", "Highland Park", "3-in-1 snowboard jacket"),

        _listing("2000000060", "Burton Cargo snowboard pants size 32", 70, "pants", "Pasadena", "snowboard pants 10k waterproof"),
    ]
    await listings.insert_many([listing.model_dump() for listing in sample_listings])

    print(f"inserted: 1 query, 1 shopping_list, {len(sample_listings)} listings")
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