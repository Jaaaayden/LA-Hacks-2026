import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel, Field

load_dotenv()

app = FastAPI()


def query_claude(
    prompt: str,
    *,
    api_key: str | None = None,
    system: str | None = None,
    model: str = "claude-sonnet-4-20250514",
    max_tokens: int = 1024,
) -> str:
    """Send `prompt` to Claude; returns the assistant text. Uses `api_key` or `ANTHROPIC_API_KEY`."""
    key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("Missing API key: pass api_key or set ANTHROPIC_API_KEY")
    client = Anthropic(api_key=key)
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    out: list[str] = []
    for block in msg.content:
        if hasattr(block, "text"):
            out.append(block.text)
    return "".join(out)


class ClaudeRequest(BaseModel):
    prompt: str
    api_key: str | None = None
    system: str | None = None
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = Field(default=1024, ge=1, le=8192)


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "ok"}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/claude")
def claude_route(body: ClaudeRequest) -> dict[str, str]:
    text = query_claude(
        body.prompt,
        api_key=body.api_key,
        system=body.system,
        model=body.model,
        max_tokens=body.max_tokens,
    )
    return {"text": text}
