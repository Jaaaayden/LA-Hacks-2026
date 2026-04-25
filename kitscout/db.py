import os

import certifi
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

load_dotenv()

_uri = os.environ["MONGODB_URI"]
_client = AsyncIOMotorClient(_uri, tlsCAFile=certifi.where())
_db = _client["kitscout"]

listings = _db["listings"]
item_comps = _db["item_comps"]
offers = _db["offers"]
queries = _db["queries"]


async def ping() -> dict:
    return await _client.admin.command("ping")
