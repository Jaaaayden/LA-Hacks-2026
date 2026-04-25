import sys
from pathlib import Path
from typing import Literal

from anthropic import Anthropic
from pydantic import BaseModel, Field

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 1024

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "intent_parser.txt"
SYSTEM_PROMPT = PROMPT_PATH.read_text()


class UserDetails(BaseModel):
    age: int | None = None
    occupation: str | None = None
    constraints: list[str] | None = None


class _ExtractedIntent(BaseModel):
    hobby: str | None = None
    budget_usd: float | None = None
    location: str | None = None
    skill_level: Literal["beginner", "intermediate", "advanced"] | None = None
    user_details: UserDetails = Field(default_factory=UserDetails)


class ParsedIntent(_ExtractedIntent):
    raw_query: str


def parse_intent(query: str, *, client: Anthropic | None = None) -> ParsedIntent:
    client = client or Anthropic()
    response = client.messages.parse(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": query}],
        output_format=_ExtractedIntent,
    )
    extracted = response.parsed_output
    if extracted is None:
        raise RuntimeError(
            f"LLM did not return a structured response (stop_reason={response.stop_reason})"
        )
    return ParsedIntent(raw_query=query, **extracted.model_dump())


def main() -> int:
    if len(sys.argv) < 2:
        print(
            'usage: python -m backend.services.intent_parser "<your query>"',
            file=sys.stderr,
        )
        return 1
    query = " ".join(sys.argv[1:])
    print(parse_intent(query).model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
