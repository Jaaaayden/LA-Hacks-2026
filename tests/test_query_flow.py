import asyncio

from bson import ObjectId

from backend.services import gen_followup
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
        if query.get("_id") != self.inserted_id or not self.inserted:
            return
        doc = self.inserted[0]
        for key, value in update.get("$set", {}).items():
            doc[key] = value
        push = update.get("$push", {})
        for key, value in push.items():
            doc.setdefault(key, []).append(value)


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
    assert result["done"] is False
    assert result["questions_asked_count"] == 1
    assert fake_queries.inserted[0]["followup_questions"] == ["What is your boot size?"]
    assert fake_queries.inserted[0]["followup_question_history"] == [
        "What is your boot size?"
    ]
    assert fake_queries.inserted[0]["parsed_intent"]["other"][0]["key"] == "boot_size"
    assert fake_queries.inserted[0]["questions_asked_count"] == 1


def test_followup_flags_skip_user_deferred_answers() -> None:
    intent = {
        "hobby": "skiing",
        "other": [{"key": "din_setting", "label": "DIN setting", "value": None}],
        "raw_query": [
            "Q: What is your DIN setting?\nA: I don't know, please calculate it."
        ],
    }

    assert gen_followup._unanswered_flags(intent) == []


def test_complete_query_session_returns_more_followups(monkeypatch) -> None:
    fake_queries = _FakeQueries()
    fake_shopping_lists = _FakeShoppingLists()
    fake_queries.inserted.append(
        {
            "_id": fake_queries.inserted_id,
            "raw_messages": ["I want to snowboard"],
            "parsed_intent": {
                "hobby": "snowboarding",
                "budget_usd": None,
                "other": [{"key": "boot_size", "label": "Boot size", "value": None}],
            },
            "followup_questions": ["What is your budget?"],
            "followup_question_history": ["What is your budget?"],
            "questions_asked_count": 1,
            "max_followup_questions": 18,
        }
    )
    monkeypatch.setattr(query_flow, "queries", fake_queries)
    monkeypatch.setattr(query_flow, "shopping_lists", fake_shopping_lists)
    monkeypatch.setattr(
        query_flow,
        "parse_intent",
        lambda text, skeleton, model: {
            **skeleton,
            "budget_usd": 300,
            "raw_query": ["I want to snowboard", text],
        },
    )
    monkeypatch.setattr(
        query_flow,
        "gen_followup",
        lambda intent, include_hobby_other_flags, model, previous_questions: {
            "questions": ["What is your boot size?"]
        },
    )

    result = _run(
        query_flow.complete_query_session(
            str(fake_queries.inserted_id),
            "My budget is $300",
        )
    )

    assert result["done"] is False
    assert result["status"] == "followups_ready"
    assert result["followup_questions"] == ["What is your boot size?"]
    assert result["questions_asked_count"] == 2
    assert fake_shopping_lists.inserted == []
    assert fake_queries.updated[0]["update"]["$set"]["status"] == "followups_ready"
    assert fake_queries.updated[0]["update"]["$set"]["followup_question_history"] == [
        "What is your budget?",
        "What is your boot size?",
    ]


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
    monkeypatch.setattr(
        query_flow,
        "gen_followup",
        lambda intent, include_hobby_other_flags, model, previous_questions: {
            "questions": []
        },
    )

    result = _run(
        query_flow.complete_query_session(
            str(fake_queries.inserted_id),
            "My boot size is 10",
        )
    )

    assert result["shopping_list_id"] == str(fake_shopping_lists.inserted_id)
    assert result["done"] is True
    assert result["status"] == "shopping_list_created"
    assert fake_shopping_lists.inserted[0]["query_id"] == str(fake_queries.inserted_id)
    assert fake_queries.updated[0]["update"]["$set"]["status"] == "shopping_list_created"
    assert (
        fake_queries.updated[0]["update"]["$set"]["shopping_list_id"]
        == str(fake_shopping_lists.inserted_id)
    )


def test_complete_query_session_finalizes_at_question_cap(monkeypatch) -> None:
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
            "followup_questions": ["What is your boot size?"],
            "questions_asked_count": 18,
            "max_followup_questions": 18,
        }
    )
    monkeypatch.setattr(query_flow, "queries", fake_queries)
    monkeypatch.setattr(query_flow, "shopping_lists", fake_shopping_lists)
    monkeypatch.setattr(
        query_flow,
        "parse_intent",
        lambda text, skeleton, model: {
            **skeleton,
            "raw_query": ["I want to snowboard", text],
        },
    )
    monkeypatch.setattr(
        query_flow,
        "gen_followup",
        lambda intent, include_hobby_other_flags, model, previous_questions: {
            "questions": ["What terrain do you prefer?"]
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
                    "item_type": "board",
                    "search_query": "beginner snowboard",
                    "required": True,
                    "attributes": [],
                    "notes": None,
                }
            ],
        },
    )

    result = _run(
        query_flow.complete_query_session(
            str(fake_queries.inserted_id),
            "I am not sure.",
        )
    )

    assert result["done"] is True
    assert result["shopping_list_id"] == str(fake_shopping_lists.inserted_id)
    assert fake_queries.updated[0]["update"]["$set"]["status"] == "shopping_list_created"
    assert fake_queries.updated[0]["update"]["$set"]["questions_asked_count"] == 18
