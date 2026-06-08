"""Workflow node implementations.

The graph is: intake -> load_context -> classify -> route ->
(confirm_write?) -> persist -> respond, with new users diverted to a multi-turn
onboarding node. The ``persist`` node is a placeholder for non-onboarding writes;
later milestones replace it with real service calls.
"""

import uuid

from langgraph.types import interrupt

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import Intent
from lars.domain.models import ScreenshotExtraction
from lars.prompts import PromptRegistry
from lars.workflow.context import ContextLoader
from lars.workflow.nutrition import NutritionLogger
from lars.workflow.onboarding import (
    OnboardingPersister,
    format_answers,
    parse_onboarding_json,
)
from lars.workflow.pulse import PulsePersister
from lars.workflow.screenshots import ScreenshotPersister
from lars.workflow.state import GraphState

# Intents whose writes must be confirmed before persisting.
CONFIRM_INTENTS = frozenset(
    {Intent.LOG_WEIGHT, Intent.LOG_WORKOUT, Intent.CHANGE_SCHEDULE, Intent.REPORT_SKIP}
)

_AFFIRMATIVE = {"yes", "y", "confirm", "ok", "okay", "sure", "yep", "yeah", "correct"}

# Pulse-check button labels → stored values.
_RPE = {"Easy": 3, "Just right": 5, "Hard": 8, "Brutal": 10}
_ENERGY = {"Low": 1, "OK": 2, "High": 3}
_SORENESS = {"None": 1, "Some": 2, "A lot": 3}


def _is_skip(value: object) -> bool:
    return str(value).strip().lower() == "skip"

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
        screenshot_persister: ScreenshotPersister | None = None,
        pulse_persister: PulsePersister | None = None,
        nutrition_logger: NutritionLogger | None = None,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._context = context_loader
        self._persister = onboarding_persister
        self._screenshot_persister = screenshot_persister
        self._pulse_persister = pulse_persister
        self._nutrition_logger = nutrition_logger

    async def intake(self, state: GraphState) -> GraphState:
        # Read this turn's input from `incoming` (fresh turn) and reset transient
        # keys so values can't bleed across turns on a reused thread.
        incoming = state.get("incoming")
        if incoming is not None:
            text = (incoming.get("text") or "").strip()
            screenshot = incoming.get("screenshot")
        else:
            text = state.get("text", "").strip()
            screenshot = state.get("screenshot")
        return {
            "text": text,
            "screenshot": screenshot,
            "completion_id": None,
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

    async def confirm_screenshot(self, state: GraphState) -> GraphState:
        shot = state.get("screenshot") or {}
        summary = shot.get("summary") or "that screenshot"
        decision = interrupt({"message": f"Got it — {summary}. Want me to save it? (yes/no)"})
        return {"confirmed": _is_affirmative(decision)}

    async def persist_screenshot(self, state: GraphState) -> GraphState:
        if self._screenshot_persister is None:
            raise RuntimeError("screenshot persistence requires a screenshot_persister")
        extraction = ScreenshotExtraction.model_validate(state["screenshot"])
        completion_id = await self._screenshot_persister(state["telegram_id"], extraction)
        message = f"Saved ✅ {extraction.summary}".rstrip()
        return {
            "persisted": True,
            "completion_id": str(completion_id) if completion_id else None,
            "response": message,
        }

    async def pulse_check(self, state: GraphState) -> GraphState:
        rpe = interrupt(
            {
                "message": "Saved ✅ Quick check-in — how hard did that feel?",
                "options": ["Easy", "Just right", "Hard", "Brutal", "Skip"],
            }
        )
        if _is_skip(rpe):
            return {"response": "No problem — logged it. 💪"}
        energy = interrupt({"message": "And your energy?", "options": ["Low", "OK", "High"]})
        soreness = interrupt(
            {"message": "Any soreness right now?", "options": ["None", "Some", "A lot"]}
        )
        note_raw = interrupt(
            {"message": "Anything else I should know? (type it, or tap Skip)", "options": ["Skip"]}
        )
        note = None if _is_skip(note_raw) else str(note_raw)

        completion_id = state.get("completion_id")
        if self._pulse_persister is not None and completion_id:
            await self._pulse_persister(
                uuid.UUID(completion_id),
                rpe=_RPE.get(str(rpe)),
                energy=_ENERGY.get(str(energy)),
                soreness=_SORENESS.get(str(soreness)),
                note=note,
            )
        return {"response": "Got it — thanks! That helps me tune your next workout. 💪"}

    async def log_nutrition(self, state: GraphState) -> GraphState:
        if self._nutrition_logger is None:
            raise RuntimeError("nutrition logging requires a nutrition_logger")
        summary = await self._nutrition_logger.log_from_text(
            state["telegram_id"], state.get("text", "")
        )
        return {"persisted": True, "response": summary}

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
    if state.get("is_new_user"):
        return "onboarding"
    if state.get("screenshot"):
        return "confirm_screenshot"
    return "classify"


def route_after_screenshot_confirm(state: GraphState) -> str:
    return "persist_screenshot" if state.get("confirmed") else "respond"


def route_after_persist_screenshot(state: GraphState) -> str:
    shot = state.get("screenshot") or {}
    if shot.get("kind") == "workout" and state.get("completion_id"):
        return "pulse_check"
    return "end"


def route_after_classify(state: GraphState) -> str:
    intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
    if intent in CONFIRM_INTENTS:
        return "confirm_write"
    if intent == Intent.LOG_NUTRITION:
        return "log_nutrition"
    return "respond"


def route_after_confirm(state: GraphState) -> str:
    return "persist" if state.get("confirmed") else "respond"
