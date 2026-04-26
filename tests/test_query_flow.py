import asyncio

from bson import ObjectId

from backend.services import query_flow

_LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(_LOOP)


def _run(coro):
    return _LOOP.run_until_complete(coro)


class _InsertResult:
    def __init__(self, inserted_id: ObjectId) -> None:
        self.inserted_id = inserted_id


class _FakeQueries:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.updated: list[dict] = []
        self.inserted_id = ObjectId()

    async def insert_one(self, doc: dict) -> _InsertResult:
        saved = dict(doc)
        saved["_id"] = self.inserted_id
        self.inserted.append(saved)
        return _InsertResult(self.inserted_id)

    async def find_one(self, query: dict) -> dict | None:
        if query.get("_id") == self.inserted_id:
            return self.inserted[0]
        return None

    async def update_one(self, query: dict, update: dict) -> None:
        self.updated.append({"query": query, "update": update})


class _FakeShoppingLists:
    def __init__(self) -> None:
        self.inserted: list[dict] = []
        self.inserted_id = ObjectId()

    async def insert_one(self, doc: dict) -> _InsertResult:
        saved = dict(doc)
        saved["_id"] = self.inserted_id
        self.inserted.append(saved)
        return _InsertResult(self.inserted_id)


def test_create_query_session_persists_followups(monkeypatch) -> None:
    fake_queries = _FakeQueries()
    monkeypatch.setattr(query_flow, "queries", fake_queries)
    monkeypatch.setattr(
        query_flow,
        "parse_intent",
        lambda text, skeleton, model: {
            "hobby": "snowboarding",
            "budget_usd": None,
            "other": None,
            "raw_query": [text],
        },
    )

    def fake_followup(intent, include_hobby_other_flags, model, merged_intent_out):
        merged_intent_out.update(
            {
                **intent,
                "other": [{"key": "boot_size", "label": "Boot size", "value": None}],
            }
        )
        return {"questions": ["What is your boot size?"]}

    monkeypatch.setattr(query_flow, "gen_followup", fake_followup)

    result = _run(query_flow.create_query_session("I want to snowboard"))

    assert result["query_id"] == str(fake_queries.inserted_id)
    assert result["status"] == "followups_ready"
    assert fake_queries.inserted[0]["followup_questions"] == ["What is your boot size?"]
    assert fake_queries.inserted[0]["parsed_intent"]["other"][0]["key"] == "boot_size"


def test_complete_query_session_persists_shopping_list(monkeypatch) -> None:
    fake_queries = _FakeQueries()
    fake_shopping_lists = _FakeShoppingLists()
    fake_queries.inserted.append(
        {
            "_id": fake_queries.inserted_id,
            "raw_messages": ["I want to snowboard"],
            "parsed_intent": {
                "hobby": "snowboarding",
                "budget_usd": 300,
                "other": [{"key": "boot_size", "label": "Boot size", "value": None}],
            },
        }
    )
    monkeypatch.setattr(query_flow, "queries", fake_queries)
    monkeypatch.setattr(query_flow, "shopping_lists", fake_shopping_lists)
    monkeypatch.setattr(
        query_flow,
        "parse_intent",
        lambda text, skeleton, model: {
            **skeleton,
            "other": [{"key": "boot_size", "label": "Boot size", "value": "10"}],
            "raw_query": ["I want to snowboard", text],
        },
    )
    monkeypatch.setattr(
        query_flow,
        "gen_list",
        lambda intent, model: {
            "hobby": "snowboarding",
            "budget_usd": 300,
            "items": [
                {
                    "item_type": "boots",
                    "search_query": "size 10 snowboard boots",
                    "required": True,
                    "attributes": [
                        {
                            "key": "size",
                            "value": [
                                {
                                    "value": "10 US",
                                    "justification": "User provided boot size.",
                                }
                            ],
                        }
                    ],
                    "notes": None,
                }
            ],
        },
    )

    result = _run(
        query_flow.complete_query_session(
            str(fake_queries.inserted_id),
            "My boot size is 10",
        )
    )

    assert result["shopping_list_id"] == str(fake_shopping_lists.inserted_id)
    assert fake_shopping_lists.inserted[0]["query_id"] == str(fake_queries.inserted_id)
    assert fake_queries.updated[0]["update"]["$set"]["status"] == "shopping_list_created"
    assert (
        fake_queries.updated[0]["update"]["$set"]["shopping_list_id"]
        == str(fake_shopping_lists.inserted_id)
    )
