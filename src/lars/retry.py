"""A small async retry helper with exponential backoff."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")

Sleep = Callable[[float], Awaitable[None]]


async def retry_async(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Sleep = asyncio.sleep,
) -> T:
    """Call ``fn`` until it succeeds, retrying on ``exceptions`` with backoff."""
    for attempt in range(attempts):
        try:
            return await fn()
        except exceptions:
            if attempt + 1 >= attempts:
                raise
            await sleep(base_delay * (2**attempt))
    raise AssertionError("unreachable")
