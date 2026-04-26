from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.kitscout.db import ping
from backend.kitscout.schemas import ShoppingListItem
from backend.services.query_flow import (
    complete_query_session,
    create_query_session,
    get_query_session,
    get_shopping_list,
    update_shopping_list,
)
from backend.services.bargain import add_to_bargain, get_bargain_items
from backend.services.search_jobs import (
    get_candidates,
    get_search_status,
    start_search,
)

app = FastAPI(title="KitScout API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateQueryRequest(BaseModel):
    user_text: str = Field(min_length=1)


class CompleteQueryRequest(BaseModel):
    followup_text: str = Field(min_length=1)


class ShoppingListUpdateRequest(BaseModel):
    hobby: str | None = None
    budget_usd: float | None = None
    items: list[ShoppingListItem] | None = None


def _http_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message.lower():
        return HTTPException(status_code=404, detail=message)
    if "Invalid Mongo ObjectId" in message:
        return HTTPException(status_code=400, detail=message)
    return HTTPException(status_code=400, detail=message)


@app.get("/health")
async def health() -> dict[str, str]:
    await ping()
    return {"status": "ok"}


@app.post("/queries")
async def create_query(request: CreateQueryRequest) -> dict[str, Any]:
    try:
        return await create_query_session(request.user_text)
    except ValueError as exc:
        raise _http_error(exc) from exc


@app.get("/queries/{query_id}")
async def read_query(query_id: str) -> dict[str, Any]:
    try:
        query = await get_query_session(query_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    if query is None:
        raise HTTPException(status_code=404, detail=f"Query not found: {query_id}")
    return query


@app.post("/queries/{query_id}/answers")
async def complete_query(
    query_id: str,
    request: CompleteQueryRequest,
) -> dict[str, Any]:
    try:
        return await complete_query_session(query_id, request.followup_text)
    except ValueError as exc:
        raise _http_error(exc) from exc


@app.get("/shopping-lists/{shopping_list_id}")
async def read_shopping_list(shopping_list_id: str) -> dict[str, Any]:
    try:
        shopping_list = await get_shopping_list(shopping_list_id)
    except ValueError as exc:
        raise _http_error(exc) from exc
    if shopping_list is None:
        raise HTTPException(
            status_code=404,
            detail=f"Shopping list not found: {shopping_list_id}",
        )
    return shopping_list


@app.patch("/shopping-lists/{shopping_list_id}")
async def patch_shopping_list(
    shopping_list_id: str,
    request: ShoppingListUpdateRequest,
) -> dict[str, Any]:
    updates = request.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No shopping list updates provided.")
    try:
        return await update_shopping_list(shopping_list_id, updates)
    except ValueError as exc:
        raise _http_error(exc) from exc


@app.post("/shopping-lists/{shopping_list_id}/search", status_code=202)
async def start_shopping_list_search(shopping_list_id: str) -> dict[str, Any]:
    try:
        return await start_search(shopping_list_id)
    except ValueError as exc:
        if "in progress" in str(exc):
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        raise _http_error(exc) from exc


@app.get("/shopping-lists/{shopping_list_id}/search-status")
async def get_shopping_list_search_status(shopping_list_id: str) -> dict[str, Any]:
    job = await get_search_status(shopping_list_id)
    if job is None:
        raise HTTPException(status_code=404, detail="No search job for this list.")
    return job


@app.get("/shopping-lists/{shopping_list_id}/candidates")
async def get_shopping_list_candidates(
    shopping_list_id: str,
) -> dict[str, list[dict[str, Any]]]:
    return await get_candidates(shopping_list_id)


class BargainRequest(BaseModel):
    item_id: str
    listing_ids: list[str] = Field(min_length=1)


@app.post("/shopping-lists/{shopping_list_id}/bargain", status_code=201)
async def bargain_listings(
    shopping_list_id: str,
    request: BargainRequest,
) -> list[dict[str, Any]]:
    try:
        return await add_to_bargain(
            shopping_list_id, request.item_id, request.listing_ids
        )
    except ValueError as exc:
        raise _http_error(exc) from exc


@app.get("/shopping-lists/{shopping_list_id}/bargain-items")
async def list_bargain_items(shopping_list_id: str) -> list[dict[str, Any]]:
    return await get_bargain_items(shopping_list_id)
