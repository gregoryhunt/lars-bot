"""Integration: on-demand (re)generation finds/creates the next session and builds it."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import SessionStatus
from lars.persistence.models import GeneratedWorkout, PlannedSession, User
from lars.prompts import PromptRegistry
from lars.scheduler.clock import SystemClock
from lars.scheduler.service import SchedulingService
from lars.services.generation import WorkoutGenerator
from lars.services.regeneration import RegenerationService

pytestmark = pytest.mark.integration

PRESCRIPTION_JSON = (
    '{"split_label": "pull", "exercises": '
    '[{"name": "Deadlift", "sets": 3, "reps": "5"}], "session_notes": "Lighter today"}'
)


def _regeneration(
    sessions: async_sessionmaker[AsyncSession], responses: list[str]
) -> RegenerationService:
    clock = SystemClock()
    generator = WorkoutGenerator(sessions, MockModelAdapter(responses), PromptRegistry(), clock)
    scheduler = SchedulingService(sessions, clock)
    return RegenerationService(sessions, scheduler, generator, clock)


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


async def test_regenerates_existing_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 9301)
    future = dt.date.today() + dt.timedelta(days=1)
    async with sessions() as session:
        planned = PlannedSession(
            user_id=user_id,
            scheduled_date=future,
            split_label="pull",
            status=SessionStatus.GENERATED,
        )
        session.add(planned)
        await session.flush()
        session.add(
            GeneratedWorkout(
                planned_session_id=planned.id,
                prescription={"split_label": "pull", "exercises": [], "progression": "progress"},
                model="mock-model",
                prompt_version="v1",
                generated_at=dt.datetime.now(dt.UTC),
                regenerated_count=0,
            )
        )
        planned_id = planned.id
        await session.commit()

    reply = await _regeneration(sessions, [PRESCRIPTION_JSON]).generate_next(9301)

    assert "deadlift" in reply.lower()  # the new prescription was returned
    async with sessions() as session:
        workout = (
            await session.execute(
                select(GeneratedWorkout).where(GeneratedWorkout.planned_session_id == planned_id)
            )
        ).scalar_one()
    assert workout.regenerated_count == 1  # regenerated in place


async def test_no_upcoming_session_is_handled(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    # No planned session and no active schedule -> nothing to generate.
    await _make_user(sessions, 9302)
    reply = await _regeneration(sessions, [PRESCRIPTION_JSON]).generate_next(9302)
    assert "no training day" in reply.lower()
