"""Mock model adapter behavior."""

from lars.adapters.llm import Image, MockModelAdapter


async def test_returns_scripted_then_default() -> None:
    adapter = MockModelAdapter(["first"], default="fallback")
    assert await adapter.generate("p1") == "first"
    assert await adapter.generate("p2") == "fallback"
    assert adapter.prompts == ["p1", "p2"]
    assert adapter.model == "mock-model"


async def test_generate_with_images_records_prompt() -> None:
    adapter = MockModelAdapter(["described"])
    out = await adapter.generate_with_images("describe", [Image(b"bytes", "image/png")])
    assert out == "described"
    assert adapter.prompts == ["describe"]
