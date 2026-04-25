import asyncio
import sys
from datetime import datetime, timezone

from backend.services.intent_parser import ParsedIntent, parse_intent
from kitscout.db import queries
from kitscout.schemas import Query


async def record_query(query_text: str) -> tuple[ParsedIntent, str]:
    parsed = parse_intent(query_text)
    doc = Query(
        raw_query=query_text,
        parsed_intent=parsed.model_dump(),
        parsed_at=datetime.now(timezone.utc),
    )
    result = await queries.insert_one(doc.model_dump())
    return parsed, str(result.inserted_id)


async def _main() -> None:
    if len(sys.argv) < 2:
        print(
            'usage: python -m backend.services.query "<your query>"',
            file=sys.stderr,
        )
        sys.exit(1)
    text = " ".join(sys.argv[1:])
    parsed, query_id = await record_query(text)
    print(f"stored query _id: {query_id}\n")
    print(parsed.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
