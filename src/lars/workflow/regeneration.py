"""On-demand workout (re)generation interface."""

from typing import Protocol


class WorkoutRegenerator(Protocol):
    """Generates (or regenerates) the user's next workout and returns it as text."""

    async def generate_next(self, telegram_id: int, request: str | None = None) -> str: ...
