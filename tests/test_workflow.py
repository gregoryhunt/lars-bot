"""Workflow routing, onboarding short-circuit, and confirm-before-write (in-memory)."""

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from lars.adapters.llm import MockModelAdapter
from lars.prompts import PromptRegistry
from lars.workflow import build_graph, run_turn
from lars.workflow.context import StubContextLoader


def make_graph(
    intent_label: str = "unknown", *, is_new: bool = False
) -> tuple[Any, MockModelAdapter]:
    adapter = MockModelAdapter([intent_label])
    graph = build_graph(adapter, PromptRegistry(), MemorySaver(), StubContextLoader(is_new=is_new))
    return graph, adapter


def cfg(thread_id: str = "t1") -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def test_read_intent_routes_to_respond_without_persisting() -> None:
    graph, adapter = make_graph("view_plan")
    result = await graph.ainvoke({"telegram_id": 1, "text": "what's today?"}, cfg())
    assert result["intent"] == "view_plan"
    assert not result.get("persisted")
    assert "plan" in result["response"].lower()
    assert len(adapter.prompts) == 1  # classify ran once


async def test_nutrition_intent_routes_to_logger() -> None:
    class FakeLogger:
        async def log_from_text(self, telegram_id: int, text: str) -> str:
            return "Logged 1 item (~200 cal)."

    graph = build_graph(
        MockModelAdapter(["log_nutrition"]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(),
        nutrition_logger=FakeLogger(),
    )
    result = await graph.ainvoke({"telegram_id": 1, "text": "ate a banana"}, cfg())
    assert result["intent"] == "log_nutrition"
    assert result["persisted"] is True
    assert "logged" in result["response"].lower()


async def test_help_intent_is_answered_by_the_model() -> None:
    # classify -> "help"; then the converse node calls the model for the reply.
    chat_reply = "I track workouts, weight, and nutrition — try sending a screenshot."
    adapter = MockModelAdapter(["help", chat_reply])
    graph = build_graph(adapter, PromptRegistry(), MemorySaver(), StubContextLoader())
    result = await graph.ainvoke({"telegram_id": 1, "text": "what can you do?"}, cfg())
    assert result["response"] == chat_reply
    assert len(adapter.prompts) == 2  # classify + converse


async def test_new_user_routed_to_onboarding() -> None:
    graph, adapter = make_graph("view_plan", is_new=True)
    reply = await run_turn(graph, cfg(), telegram_id=1, text="hey")
    assert "call you" in reply.lower()  # asks the first onboarding question
    assert adapter.prompts == []  # classify never ran


async def test_important_write_blocks_until_confirmation() -> None:
    graph, _ = make_graph("log_weight")
    first = await graph.ainvoke({"telegram_id": 1, "text": "weighed 181"}, cfg("w1"))
    assert "__interrupt__" in first
    assert not first.get("persisted")

    resumed = await graph.ainvoke(Command(resume="yes"), cfg("w1"))
    assert resumed["persisted"] is True


async def test_rejected_write_is_not_persisted() -> None:
    graph, _ = make_graph("change_schedule")
    await graph.ainvoke({"telegram_id": 1, "text": "move leg day to saturday"}, cfg("w2"))
    resumed = await graph.ainvoke(Command(resume="no"), cfg("w2"))
    assert resumed.get("persisted") is not True
    assert "won't" in resumed["response"].lower()
