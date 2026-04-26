from backend.kitscout.db import (
    bargain_items,
    listing_search_jobs,
    listings,
    queries,
    shopping_lists,
)


async def ensure_indexes() -> None:
    await queries.create_index("status")
    await queries.create_index("shopping_list_id")

    await shopping_lists.create_index("query_id")

    await listings.create_index("platform_id", unique=True)
    await listings.create_index("query_id")
    await listings.create_index("list_id")
    await listings.create_index("item_id")
    await listings.create_index("search_query")
    await listings.create_index([("list_id", 1), ("item_id", 1)])

    await listing_search_jobs.create_index("shopping_list_id", unique=True)
    await listing_search_jobs.create_index("status")

    await bargain_items.create_index(
        [("shopping_list_id", 1), ("listing_id", 1)], unique=True
    )
    await bargain_items.create_index("shopping_list_id")
    await bargain_items.create_index("status")
