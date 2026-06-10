"""The workflow graph's shared state."""

from typing import TypedDict


class GraphState(TypedDict, total=False):
    # Input
    telegram_id: int
    incoming: dict  # {"text": str | None, "screenshot": dict | None} for a fresh turn

    # Derived during the run
    text: str
    screenshot: dict | None  # parsed ScreenshotExtraction, when this turn is a photo
    pending_write: dict | None  # parsed WriteAction awaiting confirmation
    completion_id: str | None  # workout completion id, for the pulse check
    is_new_user: bool
    intent: str
    confirmed: bool | None  # None = not applicable; False = explicitly rejected
    persisted: bool

    # Output
    response: str
