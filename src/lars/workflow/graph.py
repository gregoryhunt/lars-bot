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
    route_after_parse_write,
    route_after_persist_screenshot,
    route_after_persist_write,
    route_after_screenshot_confirm,
)
from lars.workflow.nutrition import NutritionLogger
from lars.workflow.onboarding import OnboardingPersister
from lars.workflow.pulse import PulsePersister
from lars.workflow.screenshots import ScreenshotPersister
from lars.workflow.state import GraphState
from lars.workflow.summary import SummaryProvider
from lars.workflow.writes import WriteProvider


def build_graph(
    adapter: ModelAdapter,
    registry: PromptRegistry,
    checkpointer: Any,
    context_loader: ContextLoader | None = None,
    *,
    onboarding_persister: OnboardingPersister | None = None,
    screenshot_persister: ScreenshotPersister | None = None,
    pulse_persister: PulsePersister | None = None,
    nutrition_logger: NutritionLogger | None = None,
    summary_provider: SummaryProvider | None = None,
    write_provider: WriteProvider | None = None,
) -> Any:
    """Build and compile the workflow graph with the given dependencies."""
    nodes = WorkflowNodes(
        adapter,
        registry,
        context_loader or StubContextLoader(),
        onboarding_persister,
        screenshot_persister,
        pulse_persister,
        nutrition_logger,
        summary_provider,
        write_provider,
    )

    graph = StateGraph(GraphState)  # ty: ignore[invalid-argument-type]  # TypedDict bound not recognized
    graph.add_node("intake", nodes.intake)
    graph.add_node("load_context", nodes.load_context)
    graph.add_node("onboarding", nodes.onboarding)
    graph.add_node("classify", nodes.classify)
    graph.add_node("parse_write", nodes.parse_write)
    graph.add_node("confirm_write", nodes.confirm_write)
    graph.add_node("persist_write", nodes.persist_write)
    graph.add_node("confirm_screenshot", nodes.confirm_screenshot)
    graph.add_node("persist_screenshot", nodes.persist_screenshot)
    graph.add_node("pulse_check", nodes.pulse_check)
    graph.add_node("log_nutrition", nodes.log_nutrition)
    graph.add_node("summarize", nodes.summarize)
    graph.add_node("converse", nodes.converse)
    graph.add_node("respond", nodes.respond)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "load_context")
    graph.add_conditional_edges(
        "load_context",
        route_after_context,
        {
            "onboarding": "onboarding",
            "confirm_screenshot": "confirm_screenshot",
            "classify": "classify",
        },
    )
    graph.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "parse_write": "parse_write",
            "log_nutrition": "log_nutrition",
            "summarize": "summarize",
            "converse": "converse",
            "respond": "respond",
        },
    )
    graph.add_conditional_edges(
        "parse_write", route_after_parse_write, {"confirm_write": "confirm_write", "end": END}
    )
    graph.add_conditional_edges(
        "confirm_write",
        route_after_confirm,
        {"persist_write": "persist_write", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "persist_write", route_after_persist_write, {"pulse_check": "pulse_check", "end": END}
    )
    graph.add_conditional_edges(
        "confirm_screenshot",
        route_after_screenshot_confirm,
        {"persist_screenshot": "persist_screenshot", "respond": "respond"},
    )
    graph.add_conditional_edges(
        "persist_screenshot",
        route_after_persist_screenshot,
        {"pulse_check": "pulse_check", "end": END},
    )
    graph.add_edge("onboarding", END)
    graph.add_edge("pulse_check", END)
    graph.add_edge("log_nutrition", END)
    graph.add_edge("summarize", END)
    graph.add_edge("converse", END)
    graph.add_edge("respond", END)

    return graph.compile(checkpointer=checkpointer)
