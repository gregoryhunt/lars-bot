"""Pulse check (in-memory): a workout triggers a skippable survey that persists."""

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from lars.adapters.llm import MockModelAdapter
from lars.domain.models import ScreenshotExtraction
from lars.prompts import PromptRegistry
from lars.workflow import build_graph, run_turn
from lars.workflow.context import StubContextLoader

WORKOUT = ScreenshotExtraction(
    kind="workout",
    confidence=0.95,
    summary="Strength, 52 min",
    workout_type="Strength",
    duration_min=52,
)
BODY = ScreenshotExtraction(kind="body_metrics", confidence=0.95, summary="181 lb", weight_kg=82.1)


class FakeScreenshotPersister:
    def __init__(self, completion_id: uuid.UUID) -> None:
        self._completion_id = completion_id

    async def __call__(
        self, telegram_id: int, extraction: ScreenshotExtraction
    ) -> uuid.UUID | None:
        return self._completion_id if extraction.kind == "workout" else None


class RecordingPulsePersister:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(
        self,
        completion_id: uuid.UUID,
        *,
        rpe: int | None,
        energy: int | None,
        soreness: int | None,
        note: str | None,
    ) -> None:
        self.calls.append(
            {
                "completion_id": completion_id,
                "rpe": rpe,
                "energy": energy,
                "soreness": soreness,
                "note": note,
            }
        )


def cfg(thread_id: str = "p1") -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _graph(screenshot_persister: Any, pulse_persister: Any) -> Any:
    return build_graph(
        MockModelAdapter([]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(is_new=False),
        screenshot_persister=screenshot_persister,
        pulse_persister=pulse_persister,
    )


async def test_workout_triggers_pulse_then_persists() -> None:
    completion_id = uuid.uuid4()
    pulse = RecordingPulsePersister()
    graph = _graph(FakeScreenshotPersister(completion_id), pulse)
    config = cfg()

    await run_turn(graph, config, telegram_id=1, screenshot=WORKOUT.model_dump(mode="json"))
    rpe_q = await run_turn(graph, config, telegram_id=1, text="yes")
    assert rpe_q.options == ["Easy", "Just right", "Hard", "Brutal", "Skip"]
    assert "how hard" in rpe_q.lower()

    energy_q = await run_turn(graph, config, telegram_id=1, text="Hard")
    assert energy_q.options == ["Low", "OK", "High"]
    soreness_q = await run_turn(graph, config, telegram_id=1, text="OK")
    assert soreness_q.options == ["None", "Some", "A lot"]
    note_q = await run_turn(graph, config, telegram_id=1, text="None")
    assert note_q.options == ["Skip"]
    done = await run_turn(graph, config, telegram_id=1, text="felt strong")

    assert "thanks" in done.lower()
    assert len(pulse.calls) == 1
    call = pulse.calls[0]
    assert call["completion_id"] == completion_id
    assert call["rpe"] == 8
    assert call["energy"] == 2
    assert call["soreness"] == 1
    assert call["note"] == "felt strong"


async def test_pulse_is_skippable() -> None:
    pulse = RecordingPulsePersister()
    graph = _graph(FakeScreenshotPersister(uuid.uuid4()), pulse)
    config = cfg("p2")

    await run_turn(graph, config, telegram_id=1, screenshot=WORKOUT.model_dump(mode="json"))
    await run_turn(graph, config, telegram_id=1, text="yes")
    done = await run_turn(graph, config, telegram_id=1, text="Skip")

    assert "logged it" in done.lower()
    assert pulse.calls == []


async def test_body_metrics_does_not_trigger_pulse() -> None:
    pulse = RecordingPulsePersister()
    graph = _graph(FakeScreenshotPersister(uuid.uuid4()), pulse)
    config = cfg("p3")

    await run_turn(graph, config, telegram_id=1, screenshot=BODY.model_dump(mode="json"))
    saved = await run_turn(graph, config, telegram_id=1, text="yes")

    assert "saved" in saved.lower()
    assert saved.options is None
    assert pulse.calls == []
