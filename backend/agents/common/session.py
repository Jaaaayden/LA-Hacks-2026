"""Per-sender conversation state for the Coordinator agent.

The real conversation state (parsed_intent, followup_questions, shopping_list)
lives in MongoDB via teammate's `queries` collection. This module only maps
ASI:One sender_address → the Mongo `query_id` that owns that conversation.

In-memory dict with TTL sweep. Single-process, asyncio — no locking needed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional


@dataclass
class Session:
    sender: str
    query_id: Optional[str] = None
    shopping_list_id: Optional[str] = None
    payment_committed: bool = False
    payment_reference: Optional[str] = None
    parsed_intent: dict = field(default_factory=dict)
    last_seen: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ConversationStore:
    def __init__(self, ttl_minutes: int = 30) -> None:
        self._sessions: dict[str, Session] = {}
        self._ttl = timedelta(minutes=ttl_minutes)

    def get(self, sender: str) -> Session:
        sess = self._sessions.get(sender)
        if not sess:
            sess = Session(sender=sender)
            self._sessions[sender] = sess
        sess.last_seen = datetime.now(timezone.utc)
        return sess

    def reset(self, sender: str) -> None:
        self._sessions.pop(sender, None)

    def gc(self) -> int:
        """Drop sessions older than TTL. Returns number swept."""
        cutoff = datetime.now(timezone.utc) - self._ttl
        stale = [k for k, v in self._sessions.items() if v.last_seen < cutoff]
        for k in stale:
            self._sessions.pop(k, None)
        return len(stale)
