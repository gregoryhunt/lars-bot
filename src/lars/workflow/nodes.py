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
from lars.workflow.summary import SummaryProvider
from lars.workflow.writes import WriteProvider

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
    ("weight", "And what do you weigh right now? (e.g. 180 lb or 82 kg)"),
    (
        "activity",
        "Outside of workouts, how active is your typical day — sedentary, lightly "
        "active, moderately active, very active, or extra active?",
    ),
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

# Honest, deterministic placeholders for intents whose feature isn't built yet.
_PLACEHOLDER_RESPONSES: dict[Intent, str] = {
    Intent.VIEW_PLAN: (
        "I don't have a plan view yet — but I send each workout the night before "
        "your training day. A trends/plan view is on the way."
    ),
    Intent.REQUEST_GENERATION: (
        "I generate your workout automatically the night before — on-demand "
        "generation is coming soon."
    ),
}

# Conversational intents Lars answers in his own voice (model-driven).
_CONVERSE_INTENTS = frozenset({Intent.HELP, Intent.UNKNOWN})


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
        summary_provider: SummaryProvider | None = None,
        write_provider: WriteProvider | None = None,
    ) -> None:
        self._adapter = adapter
        self._registry = registry
        self._context = context_loader
        self._persister = onboarding_persister
        self._screenshot_persister = screenshot_persister
        self._pulse_persister = pulse_persister
        self._nutrition_logger = nutrition_logger
        self._summary = summary_provider
        self._writes = write_provider

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
            "pending_write": None,
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

    async def parse_write(self, state: GraphState) -> GraphState:
        if self._writes is None:
            raise RuntimeError("text writes require a write_provider")
        action = await self._writes.parse(
            state["telegram_id"], state.get("intent", ""), state.get("text", "")
        )
        if not action:
            return {"response": "I didn't quite catch that — could you say it another way?"}
        return {"pending_write": action}

    async def confirm_write(self, state: GraphState) -> GraphState:
        # Pauses the graph until the user responds (resumed via Command(resume=...)).
        summary = (state.get("pending_write") or {}).get("summary") or "that change"
        decision = interrupt({"message": f"{summary} — want me to go ahead? (yes/no)"})
        return {"confirmed": _is_affirmative(decision)}

    async def persist_write(self, state: GraphState) -> GraphState:
        if self._writes is None:
            raise RuntimeError("text writes require a write_provider")
        response, completion_id = await self._writes.persist(
            state["telegram_id"], state.get("pending_write") or {}
        )
        return {"persisted": True, "completion_id": completion_id, "response": response}

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

    async def summarize(self, state: GraphState) -> GraphState:
        if self._summary is None:
            raise RuntimeError("summaries require a summary_provider")
        period_days = 30 if "month" in state.get("text", "").lower() else 7
        text = await self._summary.summarize(state["telegram_id"], period_days)
        return {"response": text}

    async def converse(self, state: GraphState) -> GraphState:
        reply = await self._adapter.generate(
            self._registry.render("chat", message=state.get("text", "")),
            system=self._registry.persona(),
        )
        return {"response": reply}

    async def respond(self, state: GraphState) -> GraphState:
        if state.get("confirmed") is False:
            return {"response": "No problem — I won't make that change."}
        intent = Intent.parse(state.get("intent", Intent.UNKNOWN.value))
        fallback = "I'm not sure I caught that — mind saying it another way?"
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
        return "parse_write"
    if intent == Intent.LOG_NUTRITION:
        return "log_nutrition"
    if intent == Intent.VIEW_TRENDS:
        return "summarize"
    if intent in _CONVERSE_INTENTS:
        return "converse"
    return "respond"


def route_after_parse_write(state: GraphState) -> str:
    return "confirm_write" if state.get("pending_write") else "end"


def route_after_confirm(state: GraphState) -> str:
    return "persist_write" if state.get("confirmed") else "respond"


def route_after_persist_write(state: GraphState) -> str:
    pending = state.get("pending_write") or {}
    if pending.get("kind") == "workout" and state.get("completion_id"):
        return "pulse_check"
    return "end"
