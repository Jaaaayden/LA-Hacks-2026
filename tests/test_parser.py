import os

import pytest

from backend.services.intent_parser import ParsedIntent, UserDetails, parse_intent


def test_schema_defaults() -> None:
    intent = ParsedIntent(raw_query="x")
    assert intent.hobby is None
    assert intent.budget_usd is None
    assert intent.location is None
    assert intent.skill_level is None
    assert intent.user_details == UserDetails()
    assert intent.user_details.age is None
    assert intent.user_details.occupation is None
    assert intent.user_details.constraints is None
    assert intent.raw_query == "x"


pytestmark_integration = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytestmark_integration
@pytest.mark.integration
def test_happy_path() -> None:
    intent = parse_intent("I want to get into snowboarding, $250 budget, in LA")
    assert intent.hobby == "snowboarding"
    assert intent.budget_usd == 250.0
    assert intent.location is not None
    assert "la" in intent.location.lower() or "angeles" in intent.location.lower()
    assert intent.raw_query == "I want to get into snowboarding, $250 budget, in LA"


@pytestmark_integration
@pytest.mark.integration
def test_missing_budget() -> None:
    intent = parse_intent("I want to start snowboarding in LA")
    assert intent.hobby == "snowboarding"
    assert intent.budget_usd is None


@pytestmark_integration
@pytest.mark.integration
def test_non_usd_currency() -> None:
    intent = parse_intent("I have £200 to start photography in London")
    assert intent.hobby == "photography"
    assert intent.location is not None and "london" in intent.location.lower()
    assert intent.budget_usd is not None
    assert 240 <= intent.budget_usd <= 270


@pytestmark_integration
@pytest.mark.integration
def test_vague_hobby() -> None:
    intent = parse_intent("I wanna get outdoorsy")
    assert intent.budget_usd is None
    assert intent.location is None


@pytestmark_integration
@pytest.mark.integration
def test_no_hobby() -> None:
    intent = parse_intent("hi there")
    assert intent.hobby is None
    assert intent.budget_usd is None
    assert intent.location is None


@pytestmark_integration
@pytest.mark.integration
def test_user_details_extraction() -> None:
    intent = parse_intent(
        "I'm a 21yo college student with no car, want to learn pottery in LA, $150"
    )
    assert intent.hobby == "pottery"
    assert intent.budget_usd == 150.0
    assert intent.user_details.age == 21
    assert intent.user_details.occupation is not None
    assert "student" in intent.user_details.occupation.lower()
    assert intent.user_details.constraints is not None
    assert any("car" in c.lower() for c in intent.user_details.constraints)
