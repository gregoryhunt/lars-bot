"""Anthropic (Claude) implementation of the model adapter."""

import base64
from collections.abc import Sequence
from typing import Any

from anthropic import AsyncAnthropic, omit

from lars.adapters.llm.base import Image


class AnthropicAdapter:
    """Calls the Claude API behind the ModelAdapter Protocol."""

    def __init__(self, api_key: str, model: str, *, max_tokens: int = 2048) -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._max_tokens = max_tokens

    @property
    def model(self) -> str:
        return self._model

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        # Typed Any: the SDK's MessageParam TypedDicts are too strict to satisfy
        # with plain dict literals; the shape is correct at runtime.
        messages: list[Any] = [{"role": "user", "content": prompt}]
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system if system is not None else omit,
            messages=messages,
        )
        return _text(message)

    async def generate_with_images(
        self, prompt: str, images: Sequence[Image], *, system: str | None = None
    ) -> str:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": base64.b64encode(image.data).decode("ascii"),
                },
            }
            for image in images
        ]
        content.append({"type": "text", "text": prompt})
        messages: list[Any] = [{"role": "user", "content": content}]
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system if system is not None else omit,
            messages=messages,
        )
        return _text(message)


def _text(message: Any) -> str:
    return "".join(
        block.text for block in message.content if getattr(block, "type", None) == "text"
    )
