"""Nutrition logging interface (concrete impl lives in services)."""

from typing import Protocol


class NutritionLogger(Protocol):
    """Logs food from a free-text description and returns a reply with totals."""

    async def log_from_text(self, telegram_id: int, text: str) -> str: ...
