"""Summary provider interface (concrete impl lives in services)."""

from typing import Protocol


class SummaryProvider(Protocol):
    """Produces a friendly period summary for a user."""

    async def summarize(self, telegram_id: int, period_days: int = 7) -> str: ...
