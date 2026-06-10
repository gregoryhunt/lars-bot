"""Integration: workout generation persists a prescription with guardrails."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import CompletionSource, SessionStatus
from lars.persistence.models import (
    Event,
    GeneratedWorkout,
    PlannedSession,
    PulseCheck,
    User,
    WorkoutCompletion,
)
from lars.prompts import PromptRegistry
from lars.scheduler.clock import SystemClock
from lars.services.generation import WorkoutGenerator

pytestmark = pytest.mark.integration

PRESCRIPTION_JSON = (
    '{"split_label": "pull", "exercises": ['
    '{"name": "Deadlift", "sets": 3, "reps": "5", "target_load": "225 lb"}], '
    '"session_notes": "Solid pull day"}'
)


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


async def _add_session(
    sessions: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    scheduled_date: dt.date,
    split: str,
    status: SessionStatus = SessionStatus.PLANNED,
) -> uuid.UUID:
    async with sessions() as session:
        planned = PlannedSession(
            user_id=user_id, scheduled_date=scheduled_date, split_label=split, status=status
        )
        session.add(planned)
        await session.flush()
        planned_id = planned.id
        await session.commit()
    return planned_id


def _generator(
    sessions: async_sessionmaker[AsyncSession], responses: list[str]
) -> WorkoutGenerator:
    return WorkoutGenerator(sessions, MockModelAdapter(responses), PromptRegistry(), SystemClock())


async def test_generate_persists_valid_prescription(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7001)
    planned_id = await _add_session(sessions, user_id, dt.date(2026, 6, 5), "pull")

    result = await _generator(sessions, [PRESCRIPTION_JSON]).generate(planned_id)

    assert result is not None
    assert result.prescription.split_label == "pull"
    assert result.prescription.exercises[0].name == "Deadlift"
    assert result.regenerated is False

    async with sessions() as session:
        workout = (
            await session.execute(
                select(GeneratedWorkout).where(
                    GeneratedWorkout.planned_session_id == planned_id
                )
            )
        ).scalar_one()
        planned = await session.get(PlannedSession, planned_id)
        events = (
            await session.execute(
                select(Event).where(
                    Event.user_id == user_id, Event.event_type == "workout_generated"
                )
            )
        ).scalars().all()
    assert workout.regenerated_count == 0
    assert planned is not None and planned.status is SessionStatus.GENERATED
    assert len(events) == 1  # audit event emitted


async def test_user_request_is_passed_into_the_prompt(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7006)
    planned_id = await _add_session(sessions, user_id, dt.date(2026, 6, 5), "pull")
    adapter = MockModelAdapter([PRESCRIPTION_JSON])
    generator = WorkoutGenerator(sessions, adapter, PromptRegistry(), SystemClock())

    await generator.generate(planned_id, note="make it lighter and shorter")

    assert "make it lighter and shorter" in adapter.prompts[0]


async def test_progress_when_no_history(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7002)
    planned_id = await _add_session(sessions, user_id, dt.date(2026, 6, 5), "pull")

    result = await _generator(sessions, [PRESCRIPTION_JSON]).generate(planned_id)
    assert result is not None
    assert result.progression == "progress"


async def test_deload_after_missed_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7003)
    await _add_session(sessions, user_id, dt.date(2026, 6, 1), "pull", SessionStatus.MISSED)
    planned_id = await _add_session(sessions, user_id, dt.date(2026, 6, 8), "pull")

    result = await _generator(sessions, [PRESCRIPTION_JSON]).generate(planned_id)
    assert result is not None
    assert result.progression == "deload"


async def test_hold_when_last_pulse_was_hard(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7005)
    prior_id = await _add_session(
        sessions, user_id, dt.date(2026, 6, 1), "pull", SessionStatus.COMPLETED
    )
    async with sessions() as session:
        completion = WorkoutCompletion(
            user_id=user_id,
            planned_session_id=prior_id,
            source=CompletionSource.APPLE_FITNESS_SCREENSHOT,
            performed_at=dt.datetime(2026, 6, 1, 18, 0, tzinfo=dt.UTC),
        )
        session.add(completion)
        await session.flush()
        session.add(PulseCheck(completion_id=completion.id, rpe=8))
        await session.commit()
    current_id = await _add_session(sessions, user_id, dt.date(2026, 6, 8), "pull")

    result = await _generator(sessions, [PRESCRIPTION_JSON]).generate(current_id)
    assert result is not None
    assert result.progression == "hold"


async def test_no_silent_regeneration(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 7004)
    planned_id = await _add_session(sessions, user_id, dt.date(2026, 6, 5), "pull")
    adapter = MockModelAdapter([PRESCRIPTION_JSON, PRESCRIPTION_JSON])
    generator = WorkoutGenerator(sessions, adapter, PromptRegistry(), SystemClock())

    await generator.generate(planned_id)
    again = await generator.generate(planned_id)  # no explicit regenerate
    assert again is not None and again.regenerated is False
    assert len(adapter.prompts) == 1  # the model was not called the second time

    regenerated = await generator.generate(planned_id, allow_regenerate=True)
    assert regenerated is not None and regenerated.regenerated is True
    assert len(adapter.prompts) == 2

    async with sessions() as session:
        workout = (
            await session.execute(
                select(GeneratedWorkout).where(
                    GeneratedWorkout.planned_session_id == planned_id
                )
            )
        ).scalar_one()
    assert workout.regenerated_count == 1
