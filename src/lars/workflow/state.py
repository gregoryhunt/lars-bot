"""The workflow graph's shared state."""

from typing import TypedDict


class GraphState(TypedDict, total=False):
    # Input
    telegram_id: int
    text: str

    # Derived during the run
    is_new_user: bool
    intent: str
    confirmed: bool | None  # None = not applicable; False = explicitly rejected
    persisted: bool

    # Output
    response: str
