"""A small clock abstraction so time-dependent logic is testable."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    """The real clock: timezone-aware UTC now."""

    def now(self) -> datetime:
        return datetime.now(UTC)
