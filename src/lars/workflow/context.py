"""Loading per-user context for the workflow.

M3 ships a stub; M4 replaces it with a loader backed by the users table so that
a first-time user is routed into onboarding.
"""

from typing import Protocol


class ContextLoader(Protocol):
    async def is_new_user(self, telegram_id: int) -> bool: ...


class StubContextLoader:
    """A no-DB loader; treats users as existing unless configured otherwise."""

    def __init__(self, *, is_new: bool = False) -> None:
        self._is_new = is_new

    async def is_new_user(self, telegram_id: int) -> bool:
        return self._is_new
