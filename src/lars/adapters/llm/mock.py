"""In-memory model adapter for tests: returns scripted responses."""

from collections.abc import Sequence

from lars.adapters.llm.base import Image


class MockModelAdapter:
    """Returns queued responses in order, then a default. Records prompts seen."""

    def __init__(self, responses: Sequence[str] | None = None, *, default: str = "") -> None:
        self._responses = list(responses or [])
        self._default = default
        self.prompts: list[str] = []

    @property
    def model(self) -> str:
        return "mock-model"

    def _next(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._responses.pop(0) if self._responses else self._default

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return self._next(prompt)

    async def generate_with_images(
        self, prompt: str, images: Sequence[Image], *, system: str | None = None
    ) -> str:
        return self._next(prompt)
