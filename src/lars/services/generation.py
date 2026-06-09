"""Workout generation: build context, prompt the model, persist a prescription.

Deterministic guardrails live here (split resolution, dedup / no silent
regeneration, deload-after-skip); exercise selection and progression detail are
model-driven within those rails.
"""

import json
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import SessionStatus
from lars.domain.models import WorkoutPrescription
from lars.persistence.models import (
    Event,
    GeneratedWorkout,
    PlannedSession,
    PulseCheck,
    User,
    WorkoutCompletion,
)
from lars.prompts import PromptRegistry
from lars.scheduler.clock import Clock
from lars.services.metrics import HealthMetricsService

_DONE_STATES = (SessionStatus.COMPLETED, SessionStatus.SKIPPED, SessionStatus.MISSED)
_PROMPT_VERSION = "v1"
_HARD_RPE = 8


@dataclass(frozen=True)
class GenerationResult:
    prescription: WorkoutPrescription
    progression: str  # "progress" | "hold" | "deload"
    regenerated: bool


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def format_prescription(prescription: WorkoutPrescription) -> str:
    """Render a prescription as a Telegram-friendly message."""
    lines = [f"Here's your {prescription.split_label} workout 💪"]
    for index, exercise in enumerate(prescription.exercises, start=1):
        parts = [exercise.name]
        if exercise.sets and exercise.reps:
            parts.append(f"{exercise.sets}x{exercise.reps}")
        if exercise.target_load:
            parts.append(f"@ {exercise.target_load}")
        elif exercise.target_duration_min:
            parts.append(f"{exercise.target_duration_min:g} min")
        lines.append(f"{index}) " + " ".join(parts))
    if prescription.session_notes:
        lines.append(prescription.session_notes)
    return "\n".join(lines)


class WorkoutGenerator:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapter: ModelAdapter,
        registry: PromptRegistry,
        clock: Clock,
        metrics_service: HealthMetricsService | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._adapter = adapter
        self._registry = registry
        self._clock = clock
        self._metrics = metrics_service

    async def generate(
        self, planned_session_id: uuid.UUID, *, allow_regenerate: bool = False
    ) -> GenerationResult | None:
        async with self._sessionmaker() as session:
            planned = await session.get(PlannedSession, planned_session_id)
            if planned is None:
                return None

            existing = await self._existing_workout(session, planned_session_id)
            if existing is not None and not allow_regenerate:
                # No silent regeneration: return what's already there.
                stored = existing.prescription
                return GenerationResult(
                    prescription=WorkoutPrescription.model_validate(stored),
                    progression=str(stored.get("progression", "progress")),
                    regenerated=False,
                )

            user = (
                await session.execute(
                    select(User)
                    .where(User.id == planned.user_id)
                    .options(selectinload(User.profile), selectinload(User.goals))
                )
            ).scalar_one_or_none()
            last = await self._last_comparable(session, planned)
            progression = await self._progression(session, last)

            prescription = await self._call_model(session, planned, user, last, progression)
            # Deterministic split resolution: the split is owned by the schedule.
            prescription.split_label = planned.split_label

            stored = {**prescription.model_dump(), "progression": progression}
            regenerated = existing is not None
            if existing is not None:
                existing.prescription = stored
                existing.regenerated_count += 1
                existing.generated_at = self._clock.now()
                existing.model = self._adapter.model
            else:
                session.add(
                    GeneratedWorkout(
                        planned_session_id=planned_session_id,
                        prescription=stored,
                        model=self._adapter.model,
                        prompt_version=_PROMPT_VERSION,
                        generated_at=self._clock.now(),
                        regenerated_count=0,
                    )
                )
            planned.status = SessionStatus.GENERATED
            session.add(
                Event(
                    user_id=planned.user_id,
                    event_type="workout_generated",
                    payload={"split": planned.split_label, "progression": progression},
                )
            )
            await session.commit()
            return GenerationResult(prescription, progression, regenerated)

    async def _existing_workout(
        self, session: AsyncSession, planned_session_id: uuid.UUID
    ) -> GeneratedWorkout | None:
        return (
            await session.execute(
                select(GeneratedWorkout).where(
                    GeneratedWorkout.planned_session_id == planned_session_id
                )
            )
        ).scalar_one_or_none()

    async def _last_comparable(
        self, session: AsyncSession, planned: PlannedSession
    ) -> PlannedSession | None:
        return (
            await session.execute(
                select(PlannedSession)
                .where(
                    PlannedSession.user_id == planned.user_id,
                    PlannedSession.split_label == planned.split_label,
                    PlannedSession.scheduled_date < planned.scheduled_date,
                    PlannedSession.status.in_(_DONE_STATES),
                )
                .order_by(PlannedSession.scheduled_date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _last_pulse(
        self, session: AsyncSession, planned: PlannedSession
    ) -> PulseCheck | None:
        return (
            await session.execute(
                select(PulseCheck)
                .join(WorkoutCompletion, PulseCheck.completion_id == WorkoutCompletion.id)
                .where(WorkoutCompletion.planned_session_id == planned.id)
                .limit(1)
            )
        ).scalar_one_or_none()

    async def _progression(
        self, session: AsyncSession, last: PlannedSession | None
    ) -> str:
        if last is None:
            return "progress"
        if last.status in (SessionStatus.SKIPPED, SessionStatus.MISSED):
            return "deload"
        pulse = await self._last_pulse(session, last)
        if pulse is not None and pulse.rpe is not None and pulse.rpe >= _HARD_RPE:
            return "hold"
        return "progress"

    async def _call_model(
        self,
        session: AsyncSession,
        planned: PlannedSession,
        user: User | None,
        last: PlannedSession | None,
        progression: str,
    ) -> WorkoutPrescription:
        last_workout = "none"
        if last is not None:
            last_gw = await self._existing_workout(session, last.id)
            if last_gw is not None:
                last_workout = json.dumps(last_gw.prescription.get("exercises", []))

        pulse = await self._last_pulse(session, last) if last is not None else None
        feedback = "none"
        if pulse is not None:
            feedback = (
                f"rpe={pulse.rpe} energy={pulse.energy} "
                f"soreness={pulse.soreness} note={pulse.note}"
            )

        profile = user.profile if user is not None else None
        experience = (
            profile.experience_level.value
            if profile and profile.experience_level
            else "unknown"
        )
        equipment = profile.equipment_access if profile and profile.equipment_access else "unknown"
        goal = user.goals[0].type.value if user and user.goals else "unknown"

        metrics_text = "unknown"
        if self._metrics is not None:
            metrics = await self._metrics.for_user(planned.user_id)
            if metrics is not None:
                metrics_text = (
                    f"BMI {metrics.bmi} ({metrics.bmi_category}), "
                    f"TDEE ~{round(metrics.tdee)} cal, "
                    f"calorie target ~{round(metrics.calorie_target)} cal/day"
                )

        prompt = self._registry.render(
            "workout_generation",
            split=planned.split_label,
            progression=progression,
            experience=experience,
            equipment=equipment,
            goal=goal,
            metrics=metrics_text,
            last_workout=last_workout,
            feedback=feedback,
        )
        raw = await self._adapter.generate(prompt, system=self._registry.persona())
        return WorkoutPrescription.model_validate(json.loads(_strip_fences(raw)))
