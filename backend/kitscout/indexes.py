from backend.kitscout.db import listings, queries, shopping_lists


async def ensure_indexes() -> None:
    await queries.create_index("status")
    await queries.create_index("shopping_list_id")

    await shopping_lists.create_index("query_id")

    await listings.create_index("platform_id", unique=True)
    await listings.create_index("query_id")
    await listings.create_index("shopping_list_id")
    await listings.create_index("search_query")
