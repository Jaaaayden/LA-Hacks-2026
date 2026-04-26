import os
from typing import Any

import httpx
from dotenv import load_dotenv

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"


async def embed_texts(
    texts: list[str],
    *,
    model: str = DEFAULT_EMBEDDING_MODEL,
) -> list[list[float]] | None:
    """Embed text with OpenAI if configured, otherwise return None.

    Returning None lets callers fall back to deterministic local scoring in
    development environments where OPENAI_API_KEY is not present.
    """
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key or not texts:
        return None

    payload: dict[str, Any] = {
        "model": os.environ.get("OPENAI_EMBEDDING_MODEL") or model,
        "input": texts,
    }
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            OPENAI_EMBEDDINGS_URL,
            headers=headers,
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

    rows = sorted(data.get("data") or [], key=lambda row: row.get("index", 0))
    embeddings: list[list[float]] = []
    for row in rows:
        embedding = row.get("embedding")
        if not isinstance(embedding, list):
            return None
        embeddings.append([float(value) for value in embedding])

    return embeddings if len(embeddings) == len(texts) else None
