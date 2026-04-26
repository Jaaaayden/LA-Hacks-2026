from kitscout.db import listings


async def ensure_indexes() -> None:
    await listings.create_index("fb_id", unique=True)
