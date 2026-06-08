"""A model adapter that retries the wrapped adapter with backoff."""

import asyncio
from collections.abc import Sequence

from lars.adapters.llm.base import Image, ModelAdapter
from lars.retry import Sleep, retry_async


class RetryingModelAdapter:
    """Wraps any ModelAdapter, retrying transient failures."""

    def __init__(
        self,
        inner: ModelAdapter,
        *,
        attempts: int = 3,
        base_delay: float = 0.5,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._inner = inner
        self._attempts = attempts
        self._base_delay = base_delay
        self._sleep = sleep

    @property
    def model(self) -> str:
        return self._inner.model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        return await retry_async(
            lambda: self._inner.generate(prompt, system=system),
            attempts=self._attempts,
            base_delay=self._base_delay,
            sleep=self._sleep,
        )

    async def generate_with_images(
        self, prompt: str, images: Sequence[Image], *, system: str | None = None
    ) -> str:
        return await retry_async(
            lambda: self._inner.generate_with_images(prompt, images, system=system),
            attempts=self._attempts,
            base_delay=self._base_delay,
            sleep=self._sleep,
        )
