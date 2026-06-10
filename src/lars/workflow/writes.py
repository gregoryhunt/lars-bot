"""Text-write interface: parse a request, then persist it after confirmation."""

from typing import Protocol


class WriteProvider(Protocol):
    """Parses a text-write request and persists the confirmed action."""

    async def parse(self, telegram_id: int, intent: str, text: str) -> dict | None:
        """Return a serializable parsed action, or None if it can't be parsed."""
        ...

    async def persist(self, telegram_id: int, action: dict) -> tuple[str, str | None]:
        """Persist the action; return (reply, workout_completion_id or None)."""
        ...
