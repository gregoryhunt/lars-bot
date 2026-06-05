"""Screenshot extraction, the clarity gate, and the confirm/persist graph flow."""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from lars.adapters.llm import Image, MockModelAdapter
from lars.domain.models import ScreenshotExtraction
from lars.prompts import PromptRegistry
from lars.services.screenshots import (
    UNCLEAR_MESSAGE,
    ScreenshotExtractor,
    needs_clarification,
    process_photo,
)
from lars.workflow import build_graph, run_turn
from lars.workflow.context import StubContextLoader

BODY_METRICS_JSON = (
    '{"kind": "body_metrics", "confidence": 0.93, '
    '"summary": "181.6 lb, 17.2% body fat on Jun 5", '
    '"performed_at": "2026-06-05T07:00:00", "weight_kg": 82.4, "body_fat_pct": 17.2}'
)

LOW_CONFIDENCE_JSON = '{"kind": "unknown", "confidence": 0.2, "summary": "blurry"}'


class RecordingScreenshotPersister:
    def __init__(self) -> None:
        self.calls: list[tuple[int, ScreenshotExtraction]] = []

    async def __call__(self, telegram_id: int, extraction: ScreenshotExtraction) -> None:
        self.calls.append((telegram_id, extraction))


def cfg(thread_id: str = "s1") -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def test_extractor_parses_vision_json() -> None:
    extractor = ScreenshotExtractor(MockModelAdapter([BODY_METRICS_JSON]), PromptRegistry())
    result = await extractor.extract(Image(b"bytes", "image/jpeg"))
    assert result.kind == "body_metrics"
    assert result.weight_kg == 82.4
    assert result.body_fat_pct == 17.2


def test_needs_clarification() -> None:
    bm = "body_metrics"
    assert needs_clarification(ScreenshotExtraction(kind="unknown", confidence=0.9))
    assert needs_clarification(ScreenshotExtraction(kind=bm, confidence=0.2, weight_kg=80))
    assert needs_clarification(ScreenshotExtraction(kind=bm, confidence=0.9))  # no weight
    assert not needs_clarification(ScreenshotExtraction(kind=bm, confidence=0.9, weight_kg=80))


async def test_low_confidence_asks_instead_of_guessing() -> None:
    extractor = ScreenshotExtractor(MockModelAdapter([LOW_CONFIDENCE_JSON]), PromptRegistry())
    # graph is never reached for an unclear photo, so pass a placeholder.
    reply = await process_photo(
        extractor, graph=None, config=cfg(), telegram_id=1, image=Image(b"x", "image/jpeg")
    )
    assert reply == UNCLEAR_MESSAGE


async def test_screenshot_confirmed_then_persisted() -> None:
    persister = RecordingScreenshotPersister()
    graph = build_graph(
        MockModelAdapter([]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(is_new=False),
        screenshot_persister=persister,
    )
    extraction = ScreenshotExtraction.model_validate_json(BODY_METRICS_JSON)
    config = cfg()

    ask = await run_turn(
        graph, config, telegram_id=1, screenshot=extraction.model_dump(mode="json")
    )
    assert "body fat" in ask.lower()  # echoes the summary
    assert persister.calls == []  # not saved until confirmed

    saved = await run_turn(graph, config, telegram_id=1, text="yes")
    assert "saved" in saved.lower()
    assert len(persister.calls) == 1
    telegram_id, saved_extraction = persister.calls[0]
    assert telegram_id == 1
    assert saved_extraction.weight_kg == 82.4


async def test_screenshot_rejected_is_not_persisted() -> None:
    persister = RecordingScreenshotPersister()
    graph = build_graph(
        MockModelAdapter([]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(is_new=False),
        screenshot_persister=persister,
    )
    extraction = ScreenshotExtraction.model_validate_json(BODY_METRICS_JSON)
    config = cfg("s2")

    await run_turn(graph, config, telegram_id=1, screenshot=extraction.model_dump(mode="json"))
    reply = await run_turn(graph, config, telegram_id=1, text="no")
    assert persister.calls == []
    assert "won't" in reply.lower()
