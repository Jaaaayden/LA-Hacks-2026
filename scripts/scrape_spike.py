"""Minimal spike: prove the Python Stagehand+Browserbase SDK can scrape FB Marketplace.

Usage:
    .venv/bin/python scripts/scrape_spike.py

Required env vars (in .env):
    ANTHROPIC_API_KEY
    BROWSERBASE_API_KEY
    BROWSERBASE_PROJECT_ID
    FB_CONTEXT_ID    (created by `node scripts/fb_login.js` once)

Goal: navigate to one Marketplace search URL, scroll once, extract listings,
print the result. If this works, the full port is greenlit.
"""

import asyncio
import json
import os
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel
from stagehand import AsyncStagehand

load_dotenv()


class ScrapedListing(BaseModel):
    title: str
    price: float
    location: str
    url: str
    image_url: str | None = None


class ScrapedListings(BaseModel):
    listings: list[ScrapedListing]


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(f"Missing required env var: {name}")
    return val


async def main() -> None:
    bb_api_key = _require_env("BROWSERBASE_API_KEY")
    bb_project_id = _require_env("BROWSERBASE_PROJECT_ID")
    fb_context_id = _require_env("FB_CONTEXT_ID")
    anthropic_key = _require_env("ANTHROPIC_API_KEY")

    query = "snowboard"
    city = "losangeles"
    max_price = 300
    url = (
        f"https://www.facebook.com/marketplace/{city}/search/"
        f"?query={query}&maxPrice={max_price}"
    )

    print(f"[spike] connecting to Stagehand...")
    async with AsyncStagehand(
        browserbase_api_key=bb_api_key,
        browserbase_project_id=bb_project_id,
        model_api_key=anthropic_key,
    ) as client:
        print(f"[spike] starting session with FB_CONTEXT_ID={fb_context_id[:8]}...")
        start_response = await client.sessions.start(
            model_name="anthropic/claude-sonnet-4-5",
            browserbase_session_create_params={
                "project_id": bb_project_id,
                "browser_settings": {
                    "context": {"id": fb_context_id, "persist": False},
                },
            },
        )
        session_id = start_response.data.session_id
        print(f"[spike] session_id={session_id}")

        try:
            print(f"[spike] navigating to {url}")
            await client.sessions.navigate(session_id, url=url)
            await asyncio.sleep(3)

            print("[spike] dismissing any modals...")
            await client.sessions.act(
                session_id,
                input="dismiss any login or cookie modal if present",
            )

            print("[spike] scrolling to load listings...")
            await client.sessions.act(
                session_id,
                input="scroll down to load more marketplace listings",
            )
            await asyncio.sleep(2)

            print("[spike] extracting listings...")
            extract_response = await client.sessions.extract(
                session_id,
                instruction=(
                    "Extract every visible Facebook Marketplace listing card on this page. "
                    "For each card return: title, numeric price in USD (0 if free), "
                    "location text under the title, the absolute https:// URL of the listing, "
                    "and the absolute https:// URL from the <img> tag's src attribute on the "
                    "listing's photo. Do NOT return element IDs, CSS selectors, or sibling "
                    "indices for image_url — only the actual https:// URL string, or null."
                ),
                schema=ScrapedListings.model_json_schema(),
            )

            print("\n[spike] === RAW RESPONSE ===")
            print(json.dumps(
                extract_response.model_dump() if hasattr(extract_response, "model_dump")
                else extract_response,
                indent=2,
                default=str,
            ))
        finally:
            print("[spike] ending session...")
            await client.sessions.end(session_id)
            print("[spike] done.")


if __name__ == "__main__":
    asyncio.run(main())
