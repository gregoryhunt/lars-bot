"""Pulse-check persistence interface (concrete DB impl lives in services)."""

import uuid
from typing import Protocol


class PulsePersister(Protocol):
    """Persists a post-workout pulse check linked to a completion."""

    async def __call__(
        self,
        completion_id: uuid.UUID,
        *,
        rpe: int | None,
        energy: int | None,
        soreness: int | None,
        note: str | None,
    ) -> None: ...
