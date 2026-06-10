"""Integration: the Postgres checkpointer persists graph state across instances."""

from typing import Any

import pytest
from langgraph.types import Command

from lars.adapters.llm import MockModelAdapter
from lars.prompts import PromptRegistry
from lars.workflow import build_graph
from lars.workflow.checkpointer import postgres_checkpointer

pytestmark = pytest.mark.integration


class FakeWriteProvider:
    async def parse(self, telegram_id: int, intent: str, text: str) -> dict[str, Any]:
        return {"kind": "weight", "summary": "Log bodyweight 82 kg"}

    async def persist(self, telegram_id: int, action: dict[str, Any]) -> tuple[str, str | None]:
        return "Saved ✅", None


def cfg(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def test_checkpoint_persists_across_instances(migrated_db: str) -> None:
    config = cfg("ck1")

    # First "process": run until the confirm-write interrupt, then tear down.
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(
            MockModelAdapter(["log_weight"]),
            PromptRegistry(),
            saver,
            write_provider=FakeWriteProvider(),
        )
        first = await graph.ainvoke({"telegram_id": 1, "text": "weighed 181"}, config)
        assert "__interrupt__" in first
        assert not first.get("persisted")

    # Second "process": a fresh saver + graph resumes from the persisted checkpoint.
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(
            MockModelAdapter([]), PromptRegistry(), saver, write_provider=FakeWriteProvider()
        )
        resumed = await graph.ainvoke(Command(resume="yes"), config)
        assert resumed["persisted"] is True
