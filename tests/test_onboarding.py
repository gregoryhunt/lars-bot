"""Onboarding flow (in-memory): collects answers, parses, and persists once."""

import json
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from lars.adapters.llm import MockModelAdapter
from lars.domain.models import OnboardingResult
from lars.prompts import PromptRegistry
from lars.workflow import build_graph, run_turn
from lars.workflow.context import StubContextLoader

ONBOARDING_JSON = json.dumps(
    {
        "display_name": "Greg",
        "age": 34,
        "sex": "male",
        "height_cm": 180.3,
        "experience_level": "intermediate",
        "equipment_access": ["full gym"],
        "goal_type": "cut",
        "target_weight_kg": 80.0,
        "timezone": "America/New_York",
        "unit_system": "imperial",
        "schedule": {"mon": "push", "wed": "pull", "fri": "legs"},
        "generation_local_time": "20:00",
    }
)

ANSWERS = [
    "Greg",
    "34, male",
    "5'11\"",
    "lose fat, maybe get to 176",
    "intermediate",
    "push mon, pull wed, legs fri",
    "full gym",
    "US Eastern",
    "imperial",
]


class RecordingPersister:
    def __init__(self) -> None:
        self.calls: list[tuple[int, OnboardingResult]] = []

    async def __call__(self, telegram_id: int, result: OnboardingResult) -> None:
        self.calls.append((telegram_id, result))


def cfg(thread_id: str = "u1") -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def make_graph(persister: RecordingPersister) -> Any:
    return build_graph(
        MockModelAdapter([ONBOARDING_JSON]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(is_new=True),
        onboarding_persister=persister,
    )


async def test_onboarding_collects_then_persists_once() -> None:
    persister = RecordingPersister()
    graph = make_graph(persister)
    config = cfg()

    first = await run_turn(graph, config, telegram_id=1, text="hey")
    assert "call you" in first.lower()

    reply = first
    for i, answer in enumerate(ANSWERS):
        reply = await run_turn(graph, config, telegram_id=1, text=answer)
        if i < len(ANSWERS) - 1:
            assert persister.calls == []  # nothing persisted until fully answered

    assert len(persister.calls) == 1
    telegram_id, result = persister.calls[0]
    assert telegram_id == 1
    assert result.display_name == "Greg"
    assert result.goal_type.value == "cut"
    assert "all set" in reply.lower()


async def test_onboarding_resumes_from_checkpoint() -> None:
    persister = RecordingPersister()
    graph = make_graph(persister)
    config = cfg("u2")

    await run_turn(graph, config, telegram_id=2, text="hi")
    second_question = await run_turn(graph, config, telegram_id=2, text="Greg")

    # We advanced to the next question and have not persisted yet.
    assert "old" in second_question.lower()
    assert persister.calls == []
