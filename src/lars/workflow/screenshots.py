"""Screenshot persistence interface (concrete DB impl lives in services)."""

import uuid
from typing import Protocol

from lars.domain.models import ScreenshotExtraction


class ScreenshotPersister(Protocol):
    """Persists a confirmed screenshot extraction; returns a workout completion id."""

    async def __call__(
        self, telegram_id: int, extraction: ScreenshotExtraction
    ) -> uuid.UUID | None: ...
