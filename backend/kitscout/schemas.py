from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class Location(BaseModel):
    city: str | None = None
    state: str | None = None
    lat: float | None = None
    lng: float | None = None
    raw: str | None = None


class Query(BaseModel):
    raw_messages: list[str]
    parsed_intent: dict[str, Any]
    status: Literal[
        "needs_followup",
        "ready_for_list",
        "shopping_list_created",
        "failed",
    ]
    created_at: datetime
    updated_at: datetime
    followup_questions: list[str] = Field(default_factory=list)
    shopping_list_id: str | None = None
    error: str | None = None


class ShoppingListValue(BaseModel):
    value: str
    justification: str


class ShoppingListAttribute(BaseModel):
    key: str
    value: list[ShoppingListValue]


class ShoppingListItem(BaseModel):
    item_type: str
    search_query: str
    required: bool
    attributes: list[ShoppingListAttribute] = Field(default_factory=list)
    notes: str | None = None


class ShoppingList(BaseModel):
    query_id: str
    hobby: str
    budget_usd: float | None = None
    items: list[ShoppingListItem]
    created_at: datetime
    source_model: str


class Listing(BaseModel):
    fb_id: str
    source: Literal["facebook_marketplace"] = "facebook_marketplace"
    url: str
    title: str
    description: str | None = None

    price_usd: float
    currency: str = "USD"

    hobby: str
    item_type: str
    condition: Literal["new", "like_new", "good", "fair", "poor"] | None = None
    size: str | None = None

    query_id: str | None = None
    shopping_list_id: str | None = None
    shopping_list_item_type: str | None = None
    search_query: str | None = None

    location: Location = Field(default_factory=Location)
    image_url: str | None = None

    posted_at: datetime | None = None
    scraped_at: datetime
    raw: dict[str, Any] = Field(default_factory=dict)
