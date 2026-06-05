"""Thin model-provider adapter interface (keeps vendor access behind a Protocol)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Image:
    """An image to send to a vision-capable model."""

    data: bytes
    media_type: str  # e.g. "image/jpeg", "image/png"


class ModelAdapter(Protocol):
    """Minimal text + vision generation surface used by the workflow."""

    @property
    def model(self) -> str: ...

    async def generate(self, prompt: str, *, system: str | None = None) -> str: ...

    async def generate_with_images(
        self, prompt: str, images: Sequence[Image], *, system: str | None = None
    ) -> str: ...
