"""Retry helper and the retrying model adapter."""

import pytest

from lars.adapters.llm import RetryingModelAdapter
from lars.retry import retry_async


async def _no_sleep(delay: float) -> None:
    return None


async def test_retries_then_succeeds() -> None:
    attempts = {"n": 0}

    async def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient")
        return "ok"

    result = await retry_async(flaky, attempts=3, sleep=_no_sleep)
    assert result == "ok"
    assert attempts["n"] == 3


async def test_raises_after_exhausting_attempts() -> None:
    async def always_fails() -> str:
        raise ValueError("down")

    with pytest.raises(ValueError):
        await retry_async(always_fails, attempts=2, sleep=_no_sleep)


class _FlakyAdapter:
    def __init__(self, failures: int) -> None:
        self._failures = failures
        self.calls = 0

    @property
    def model(self) -> str:
        return "flaky"

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        self.calls += 1
        if self.calls <= self._failures:
            raise RuntimeError("boom")
        return "done"

    async def generate_with_images(
        self, prompt: str, images: object, *, system: object = None
    ) -> str:
        return "img"


async def test_retrying_adapter_retries_generate() -> None:
    inner = _FlakyAdapter(failures=2)
    adapter = RetryingModelAdapter(inner, attempts=3, sleep=_no_sleep)
    assert await adapter.generate("p") == "done"
    assert inner.calls == 3
