from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class Location(BaseModel):
    city: str | None = None
    state: str | None = None
    lat: float | None = None
    lng: float | None = None
    raw: str | None = None


class Listing(BaseModel):
    fb_id: str
    url: str
    title: str
    description: str | None = None

    price_usd: float
    currency: str = "USD"

    hobby: str
    item_type: str
    condition: Literal["new", "like_new", "good", "fair", "poor"] | None = None
    skill_level_fit: Literal["beginner", "intermediate", "advanced"] | None = None
    size: str | None = None

    location: Location = Field(default_factory=Location)
    image_url: str | None = None

    posted_at: datetime | None = None
    scraped_at: datetime
    raw: dict = Field(default_factory=dict)


class ItemComp(BaseModel):
    hobby: str
    item_type: str
    model: str | None = None
    median_price_usd: float
    p25_usd: float | None = None
    p75_usd: float | None = None
    samples: int
    updated_at: datetime


class Query(BaseModel):
    raw_query: str
    parsed_intent: dict
    parsed_at: datetime
    offer_id: str | None = None


class Offer(BaseModel):
    query_text: str
    parsed_intent: dict
    listing_ids: list[str]
    total_price_usd: float
    rationale: str | None = None
    created_at: datetime
