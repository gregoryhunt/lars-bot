"""Assemble the Lars workflow graph."""

from typing import Any

from langgraph.graph import END, START, StateGraph

from lars.adapters.llm import ModelAdapter
from lars.prompts import PromptRegistry
from lars.workflow.context import ContextLoader, StubContextLoader
from lars.workflow.nodes import (
    WorkflowNodes,
    route_after_classify,
    route_after_confirm,
    route_after_context,
)
from lars.workflow.state import GraphState


def build_graph(
    adapter: ModelAdapter,
    registry: PromptRegistry,
    checkpointer: Any,
    context_loader: ContextLoader | None = None,
) -> Any:
    """Build and compile the workflow graph with the given dependencies."""
    nodes = WorkflowNodes(adapter, registry, context_loader or StubContextLoader())

    graph = StateGraph(GraphState)  # ty: ignore[invalid-argument-type]  # TypedDict bound not recognized
    graph.add_node("intake", nodes.intake)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("classify", nodes.classify)
    graph.add_node("confirm_write", nodes.confirm_write)
    graph.add_node("persist", nodes.persist)
    graph.add_node("respond", nodes.respond)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "load_context")
    graph.add_conditional_edges(
        "load_context", route_after_context, {"respond": "respond", "classify": "classify"}
    )
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {"confirm_write": "confirm_write", "persist": "persist", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "confirm_write", route_after_confirm, {"persist": "persist", "respond": "respond"}
    )
    graph.add_edge("persist", "respond")
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)
