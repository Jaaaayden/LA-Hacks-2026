from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

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
        "followups_ready",
        "needs_followup",
        "shopping_list_created",
        "shopping_list_edited",
        "failed",
    ]
    created_at: datetime
    updated_at: datetime
    followup_questions: list[str] = Field(default_factory=list)
    followup_question_history: list[str] = Field(default_factory=list)
    questions_asked_count: int = 0
    max_followup_questions: int = 18
    shopping_list_id: str | None = None
    error: str | None = None


class ShoppingListValue(BaseModel):
    value: str
    justification: str


class ShoppingListAttribute(BaseModel):
    key: str
    value: list[ShoppingListValue]


class ShoppingListItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    item_type: str
    search_query: str
    budget_usd: float = 0.0
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
    platform_id: str
    source: Literal["offerup"] = "offerup"
    url: str
    title: str
    description: str | None = None

    price_usd: float
    currency: str = "USD"

    hobby: str
    item_type: str
    condition: Literal["new", "like_new", "good", "fair", "poor"] | None = None
    condition_code: str | None = None
    size: str | None = None

    query_id: str | None = None
    list_id: str | None = None
    item_id: str | None = None
    search_query: str | None = None

    location: Location = Field(default_factory=Location)
    image_url: str | None = None
    image_path: str | None = None
    photos: list[dict[str, Any]] = Field(default_factory=list)

    posted_at: datetime | None = None
    post_date: str | None = None
    scraped_at: datetime
    original_price: str | None = None
    is_removed: bool | None = None
    is_local: bool | None = None
    is_firm_on_price: bool | None = None
    quantity: int | None = None
    seller: dict[str, Any] | None = None
    category: dict[str, Any] | None = None
    fulfillment: dict[str, Any] | None = None
    distance: dict[str, Any] | None = None
    relevance: Literal["relevant", "uncertain", "irrelevant"] = "uncertain"
    extracted_attributes: list[dict[str, Any]] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    attribute_notes: str | None = None
    seller_questions: list[dict[str, Any]] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class ListingSearchJob(BaseModel):
    shopping_list_id: str
    status: Literal["pending", "searching", "done", "error"]
    current_item_id: str | None = None
    current_item_type: str | None = None
    items_done: int = 0
    items_total: int = 0
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    retry_after_seconds: int | None = None
    next_retry_at: datetime | None = None
    counts: dict[str, int] = Field(default_factory=dict)


class BargainItem(BaseModel):
    shopping_list_id: str
    item_id: str            # ShoppingListItem.id (which slot this belongs to)
    item_type: str          # e.g. "board", "boots"
    listing_id: str         # OfferUp platform_id (numeric string)
    title: str
    price_usd: float
    target_price_usd: float
    url: str
    thread_url: str | None = None
    image_url: str | None = None
    location_raw: str | None = None
    status: Literal[
        "queued",
        "selected",
        "questions_sent",
        "details_received",
        "ready_to_negotiate",
        "negotiating",
        "agreed",
        "gave_up",
        "error",
    ] = "selected"
    conversation: list[dict[str, str]] = Field(default_factory=list)
    last_message: str | None = None
    last_seller_message: str | None = None
    added_at: datetime
    updated_at: datetime
    error: str | None = None
