"""Workflow node implementations.

The graph is: intake -> load_context -> classify -> route ->
(confirm_write?) -> persist -> respond. Persistence here is a placeholder for
M3; later milestones replace the ``persist`` node with real service calls.
"""

from langgraph.types import interrupt

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import Intent
from lars.prompts import PromptRegistry
from lars.workflow.context import ContextLoader
from lars.workflow.state import GraphState

# Intents whose writes must be confirmed before persisting.
CONFIRM_INTENTS = frozenset(
    {Intent.LOG_WEIGHT, Intent.LOG_WORKOUT, Intent.CHANGE_SCHEDULE, Intent.REPORT_SKIP}
)
# Writes that are low-stakes enough to persist without confirmation.
TRIVIAL_WRITE_INTENTS = frozenset({Intent.LOG_NUTRITION})

_AFFIRMATIVE = {"yes", "y", "confirm", "ok", "okay", "sure", "yep", "yeah", "correct"}

ONBOARDING_GREETING = (
    "Hi! I'm Lars. I'll get you set up with a few quick questions. "
    "(Onboarding flow arrives in the next milestone.)"
)

_PLACEHOLDER_RESPONSES: dict[Intent, str] = {
    Intent.VIEW_PLAN: "Here's where I'll show your plan. (coming soon)",
    Intent.VIEW_TRENDS: "Here's where I'll show your trends. (coming soon)",
    Intent.REQUEST_GENERATION: "I'll generate a workout for you here. (coming soon)",
    Intent.HELP: "I track your workouts, weight, and nutrition — just talk to me normally.",
    Intent.UNKNOWN: "I'm not sure I caught that — could you say it another way?",
}


def _is_affirmative(value: object) -> bool:
    return str(value).strip().lower() in _AFFIRMATIVE


class WorkflowNodes:
    def __init__(
        self,
        adapter: ModelAdapter,
        registry: PromptRegistry,
        context_loader: ContextLoader,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._context = context_loader

    async def intake(self, state: GraphState) -> GraphState:
        return {"text": state.get("text", "").strip()}

    async def load_context(self, state: GraphState) -> GraphState:
        is_new = await self._context.is_new_user(state["telegram_id"])
        return {"is_new_user": is_new}

    async def classify(self, state: GraphState) -> GraphState:
        prompt = self._registry.render(
            "intent_classification",
            intents="\n".join(f"- {i.value}" for i in Intent),
            message=state.get("text", ""),
        )
        raw = await self._adapter.generate(prompt)
        return {"intent": Intent.parse(raw).value}

    async def confirm_write(self, state: GraphState) -> GraphState:
        # Pauses the graph until the user responds (resumed via Command(resume=...)).
        decision = interrupt({"intent": state.get("intent"), "question": "Confirm this change?"})
        return {"confirmed": _is_affirmative(decision)}

    async def persist(self, state: GraphState) -> GraphState:
        # Placeholder write; real persistence lands in later milestones.
        return {"persisted": True}

    async def respond(self, state: GraphState) -> GraphState:
        if state.get("is_new_user"):
            return {"response": ONBOARDING_GREETING}
        if state.get("persisted"):
            return {"response": "Done ✅ (placeholder write — real persistence coming soon)."}
        if state.get("confirmed") is False:
            return {"response": "No problem — I won't make that change."}
        intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
        fallback = _PLACEHOLDER_RESPONSES[Intent.UNKNOWN]
        return {"response": _PLACEHOLDER_RESPONSES.get(intent, fallback)}


def route_after_context(state: GraphState) -> str:
    return "respond" if state.get("is_new_user") else "classify"


def route_after_classify(state: GraphState) -> str:
    intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
    if intent in CONFIRM_INTENTS:
        return "confirm_write"
    if intent in TRIVIAL_WRITE_INTENTS:
        return "persist"
    return "respond"


def route_after_confirm(state: GraphState) -> str:
    return "persist" if state.get("confirmed") else "respond"
