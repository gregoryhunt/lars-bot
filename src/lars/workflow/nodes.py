"""Workflow node implementations.

The graph is: intake -> load_context -> classify -> route ->
(confirm_write?) -> persist -> respond, with new users diverted to a multi-turn
onboarding node. The ``persist`` node is a placeholder for non-onboarding writes;
later milestones replace it with real service calls.
"""

from langgraph.types import interrupt

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import Intent
from lars.prompts import PromptRegistry
from lars.workflow.context import ContextLoader
from lars.workflow.onboarding import (
    OnboardingPersister,
    format_answers,
    parse_onboarding_json,
)
from lars.workflow.state import GraphState

# Intents whose writes must be confirmed before persisting.
CONFIRM_INTENTS = frozenset(
    {Intent.LOG_WEIGHT, Intent.LOG_WORKOUT, Intent.CHANGE_SCHEDULE, Intent.REPORT_SKIP}
)
# Writes that are low-stakes enough to persist without confirmation.
TRIVIAL_WRITE_INTENTS = frozenset({Intent.LOG_NUTRITION})

_AFFIRMATIVE = {"yes", "y", "confirm", "ok", "okay", "sure", "yep", "yeah", "correct"}

_ONBOARDING_QUESTIONS: list[tuple[str, str]] = [
    (
        "name",
        "Hi! I'm Lars, your coach. Let's get you set up — it takes about a minute. "
        "First, what should I call you?",
    ),
    (
        "age_and_sex",
        "Great to meet you! How old are you, and what's your biological sex "
        "(for training and nutrition math)?",
    ),
    ("height", "How tall are you? (e.g. 5'11\" or 180 cm)"),
    (
        "goal",
        "What's your main goal — lose fat, build muscle, maintain, or recomp? "
        "A target weight is optional.",
    ),
    (
        "experience",
        "How would you describe your training experience — "
        "beginner, intermediate, or advanced?",
    ),
    (
        "schedule",
        "Which days do you want to train, and what split? "
        "(e.g. Push Mon, Pull Wed, Legs Fri)",
    ),
    ("equipment", "What equipment can you access? (e.g. full gym, dumbbells only, home setup)"),
    ("timezone", "What timezone are you in? (e.g. US Eastern, Europe/London)"),
    ("units", "Last one — do you prefer imperial (lb) or metric (kg)?"),
]

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
        onboarding_persister: OnboardingPersister | None = None,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._context = context_loader
        self._persister = onboarding_persister

    async def intake(self, state: GraphState) -> GraphState:
        # Reset transient keys so values can't bleed across turns on a reused thread.
        return {
            "text": state.get("text", "").strip(),
            "intent": "",
            "is_new_user": False,
            "confirmed": None,
            "persisted": False,
            "response": "",
        }

    async def load_context(self, state: GraphState) -> GraphState:
        is_new = await self._context.is_new_user(state["telegram_id"])
        return {"is_new_user": is_new}

    async def onboarding(self, state: GraphState) -> GraphState:
        answers: dict[str, str] = {}
        for key, question in _ONBOARDING_QUESTIONS:
            answers[key] = str(interrupt({"message": question}))

        raw = await self._adapter.generate(
            self._registry.render("onboarding_extraction", answers=format_answers(answers))
        )
        result = parse_onboarding_json(raw)
        if self._persister is None:
            raise RuntimeError("onboarding requires an onboarding_persister")
        await self._persister(state["telegram_id"], result)
        return {
            "is_new_user": False,
            "response": (
                f"You're all set, {result.display_name}! I'll build your first workout the "
                "night before your next training day. After you train, send me an Apple "
                "Fitness screenshot, and a scale photo whenever you weigh in."
            ),
        }

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
        decision = interrupt({"message": "Just to confirm — should I go ahead? (yes/no)"})
        return {"confirmed": _is_affirmative(decision)}

    async def persist(self, state: GraphState) -> GraphState:
        # Placeholder write; real persistence lands in later milestones.
        return {"persisted": True}

    async def respond(self, state: GraphState) -> GraphState:
        if state.get("persisted"):
            return {"response": "Done ✅ (placeholder write — real persistence coming soon)."}
        if state.get("confirmed") is False:
            return {"response": "No problem — I won't make that change."}
        intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
        fallback = _PLACEHOLDER_RESPONSES[Intent.UNKNOWN]
        return {"response": _PLACEHOLDER_RESPONSES.get(intent, fallback)}


def route_after_context(state: GraphState) -> str:
    return "onboarding" if state.get("is_new_user") else "classify"


def route_after_classify(state: GraphState) -> str:
    intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
    if intent in CONFIRM_INTENTS:
        return "confirm_write"
    if intent in TRIVIAL_WRITE_INTENTS:
        return "persist"
    return "respond"


def route_after_confirm(state: GraphState) -> str:
    return "persist" if state.get("confirmed") else "respond"
