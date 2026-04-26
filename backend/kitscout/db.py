import os
from typing import Any

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

_DB_NAME = "kitscout"
_uri = os.environ.get("MONGODB_URI")
_client = AsyncIOMotorClient(_uri, tlsCAFile=certifi.where()) if _uri else None
_db = _client[_DB_NAME] if _client is not None else None


class _MissingCollection:
    def __init__(self, name: str) -> None:
        self.name = name

    def __getattr__(self, attr: str) -> Any:
        raise RuntimeError(
            f"MONGODB_URI is not set; cannot use Mongo collection {self.name!r}."
        )


queries = _db["queries"] if _db is not None else _MissingCollection("queries")
shopping_lists = (
    _db["shopping_lists"] if _db is not None else _MissingCollection("shopping_lists")
)
listings = _db["listings"] if _db is not None else _MissingCollection("listings")


async def ping() -> dict[str, Any]:
    if _client is None:
        raise RuntimeError("MONGODB_URI is not set; cannot ping MongoDB.")
    return await _client.admin.command("ping")
