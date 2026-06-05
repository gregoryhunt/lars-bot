"""Screenshot persistence interface (concrete DB impl lives in services)."""

from typing import Protocol

from lars.domain.models import ScreenshotExtraction


class ScreenshotPersister(Protocol):
    """Persists a confirmed screenshot extraction for a user."""

    async def __call__(self, telegram_id: int, extraction: ScreenshotExtraction) -> None: ...
