"""Integration: the Postgres checkpointer persists graph state across instances."""

from typing import Any

import pytest
from langgraph.types import Command

from lars.adapters.llm import MockModelAdapter
from lars.prompts import PromptRegistry
from lars.workflow import build_graph
from lars.workflow.checkpointer import postgres_checkpointer

pytestmark = pytest.mark.integration


def cfg(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def test_checkpoint_persists_across_instances(migrated_db: str) -> None:
    config = cfg("ck1")

    # First "process": run until the confirm-write interrupt, then tear down.
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(MockModelAdapter(["log_weight"]), PromptRegistry(), saver)
        first = await graph.ainvoke({"telegram_id": 1, "text": "weighed 181"}, config)
        assert "__interrupt__" in first
        assert "persisted" not in first

    # Second "process": a fresh saver + graph resumes from the persisted checkpoint.
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(MockModelAdapter([]), PromptRegistry(), saver)
        resumed = await graph.ainvoke(Command(resume="yes"), config)
        assert resumed["persisted"] is True
