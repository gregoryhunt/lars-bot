"""Parse and persist natural-language write requests (weight, workout, schedule, skip)."""

import json
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import BodyMetricSource, CompletionSource, SessionStatus
from lars.domain.models import WriteAction
from lars.persistence.models import (
    BodyMetric,
    Event,
    PlannedSession,
    User,
    WorkoutCompletion,
    WorkoutSchedule,
)
from lars.persistence.repositories import UserRepository
from lars.prompts import PromptRegistry
from lars.scheduler.clock import Clock

_OPEN_STATES = [SessionStatus.PLANNED, SessionStatus.GENERATED]


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def _is_valid(action: WriteAction) -> bool:
    if action.kind == "weight":
        return action.weight_kg is not None
    if action.kind == "workout":
        return True
    if action.kind == "schedule":
        return bool(action.schedule)
    if action.kind == "skip":
        return action.skip_date is not None
    return False


class WriteService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapter: ModelAdapter,
        registry: PromptRegistry,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._adapter = adapter
        self._registry = registry
        self._clock = clock

    async def _active_schedule(
        self, session: AsyncSession, user_id: object
    ) -> WorkoutSchedule | None:
        return (
            await session.execute(
                select(WorkoutSchedule)
                .where(WorkoutSchedule.user_id == user_id, WorkoutSchedule.is_active.is_(True))
                .order_by(WorkoutSchedule.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def parse(self, telegram_id: int, intent: str, text: str) -> dict | None:
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return None
            today = self._clock.now().astimezone(ZoneInfo(user.timezone)).date()
            schedule = await self._active_schedule(session, user.id)
            current = json.dumps(schedule.definition) if schedule else "none"

        prompt = self._registry.render(
            "write_extraction",
            intent=intent,
            today=today.isoformat(),
            current_schedule=current,
            message=text,
        )
        raw = await self._adapter.generate(prompt)
        try:
            action = WriteAction.model_validate(json.loads(_strip_fences(raw)))
        except Exception:
            return None
        return action.model_dump(mode="json") if _is_valid(action) else None

    async def persist(self, telegram_id: int, action: dict) -> tuple[str, str | None]:
        parsed = WriteAction.model_validate(action)
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return "Let's get you set up first — just say hi to start.", None

            tz = ZoneInfo(user.timezone)
            today = self._clock.now().astimezone(tz).date()
            response, completion_id, event_type = await self._dispatch(session, user, parsed, today)
            session.add(
                Event(
                    user_id=user.id,
                    event_type=event_type,
                    payload={"summary": parsed.summary},
                )
            )
            await session.commit()
        return response, completion_id

    async def _dispatch(
        self, session: AsyncSession, user: User, action: WriteAction, today: date
    ) -> tuple[str, str | None, str]:
        if action.kind == "weight":
            session.add(
                BodyMetric(
                    user_id=user.id,
                    measured_at=datetime.now(UTC),
                    weight_kg=action.weight_kg,
                    body_fat_pct=action.body_fat_pct,
                    source=BodyMetricSource.MANUAL,
                )
            )
            return f"Saved ✅ {action.summary}".rstrip(), None, "weight_logged"

        if action.kind == "workout":
            performed = action.performed_on or today
            completion = WorkoutCompletion(
                user_id=user.id,
                planned_session_id=await self._planned_id(session, user, performed),
                source=CompletionSource.MANUAL,
                workout_type=action.workout_type,
                duration_min=action.duration_min,
                performed_at=datetime.combine(performed, time(12, 0), tzinfo=UTC),
                confirmed_at=datetime.now(UTC),
            )
            session.add(completion)
            await session.flush()
            return f"Logged ✅ {action.summary}".rstrip(), str(completion.id), "workout_logged"

        if action.kind == "schedule":
            current = await self._active_schedule(session, user.id)
            generation_time = current.generation_local_time if current else time(20, 0)
            if current is not None:
                current.is_active = False
            session.add(
                WorkoutSchedule(
                    user_id=user.id,
                    definition=action.schedule or {},
                    generation_local_time=generation_time,
                    effective_from=today,
                    is_active=True,
                )
            )
            return f"Updated ✅ {action.summary}".rstrip(), None, "schedule_changed"

        # skip
        planned = (
            await session.execute(
                select(PlannedSession).where(
                    PlannedSession.user_id == user.id,
                    PlannedSession.scheduled_date == action.skip_date,
                    PlannedSession.status.in_(_OPEN_STATES),
                )
            )
        ).scalar_one_or_none()
        if planned is not None:
            planned.status = SessionStatus.SKIPPED
            return f"Done — {action.summary}".rstrip(), None, "session_skipped"
        return (
            "Noted — I don't see a scheduled session then, but I'll remember.",
            None,
            "session_skipped",
        )

    async def _planned_id(
        self, session: AsyncSession, user: User, day: date
    ) -> object | None:
        planned = (
            await session.execute(
                select(PlannedSession).where(
                    PlannedSession.user_id == user.id, PlannedSession.scheduled_date == day
                )
            )
        ).scalar_one_or_none()
        if planned is not None:
            planned.status = SessionStatus.COMPLETED
        return planned.id if planned is not None else None
