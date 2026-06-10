"""Integration: text-write persistence (weight, workout, schedule, skip)."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import SessionStatus
from lars.persistence.models import (
    BodyMetric,
    PlannedSession,
    User,
    WorkoutCompletion,
    WorkoutSchedule,
)
from lars.prompts import PromptRegistry
from lars.services.writes import WriteService

_NOW = dt.datetime(2026, 6, 10, 16, 0, tzinfo=dt.UTC)


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


def _service(sessions: async_sessionmaker[AsyncSession]) -> WriteService:
    # The adapter isn't used by persist(); parse() isn't exercised here.
    return WriteService(sessions, MockModelAdapter([]), PromptRegistry(), FixedClock(_NOW))


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


@pytest.mark.integration
async def test_persist_weight(sessions: async_sessionmaker[AsyncSession]) -> None:
    user_id = await _make_user(sessions, 9201)
    reply, completion_id = await _service(sessions).persist(
        9201, {"kind": "weight", "summary": "Log bodyweight 82 kg", "weight_kg": 82.0}
    )
    assert "saved" in reply.lower()
    assert completion_id is None
    async with sessions() as session:
        rows = (
            await session.execute(select(BodyMetric).where(BodyMetric.user_id == user_id))
        ).scalars().all()
    assert len(rows) == 1
    assert float(rows[0].weight_kg) == 82.0


@pytest.mark.integration
async def test_persist_workout_reconciles_and_returns_completion(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 9202)
    async with sessions() as session:
        session.add(
            PlannedSession(
                user_id=user_id,
                scheduled_date=dt.date(2026, 6, 10),
                split_label="pull",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()

    reply, completion_id = await _service(sessions).persist(
        9202,
        {
            "kind": "workout",
            "summary": "Log pull workout",
            "workout_type": "Pull",
            "duration_min": 45,
            "performed_on": "2026-06-10",
        },
    )
    assert "logged" in reply.lower()
    assert completion_id is not None  # enables the pulse check

    async with sessions() as session:
        completion = (
            await session.execute(
                select(WorkoutCompletion).where(WorkoutCompletion.user_id == user_id)
            )
        ).scalar_one()
        planned = (
            await session.execute(
                select(PlannedSession).where(PlannedSession.user_id == user_id)
            )
        ).scalar_one()
    assert completion.planned_session_id == planned.id
    assert planned.status is SessionStatus.COMPLETED


@pytest.mark.integration
async def test_persist_schedule_replaces_active(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 9203)
    async with sessions() as session:
        session.add(
            WorkoutSchedule(
                user_id=user_id,
                definition={"mon": "push", "wed": "pull", "fri": "legs"},
                generation_local_time=dt.time(20, 0),
                effective_from=dt.date(2026, 1, 1),
                is_active=True,
            )
        )
        await session.commit()

    new_def = {"mon": "push", "wed": "pull", "sat": "legs"}
    await _service(sessions).persist(
        9203, {"kind": "schedule", "summary": "Move legs to Saturday", "schedule": new_def}
    )

    async with sessions() as session:
        active = (
            await session.execute(
                select(WorkoutSchedule).where(
                    WorkoutSchedule.user_id == user_id, WorkoutSchedule.is_active.is_(True)
                )
            )
        ).scalars().all()
    assert len(active) == 1
    assert active[0].definition == new_def
    assert active[0].generation_local_time == dt.time(20, 0)  # preserved


@pytest.mark.integration
async def test_persist_skip_marks_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 9204)
    async with sessions() as session:
        session.add(
            PlannedSession(
                user_id=user_id,
                scheduled_date=dt.date(2026, 6, 10),
                split_label="push",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()

    reply, _ = await _service(sessions).persist(
        9204, {"kind": "skip", "summary": "Skip today", "skip_date": "2026-06-10"}
    )
    assert "done" in reply.lower()
    async with sessions() as session:
        planned = (
            await session.execute(
                select(PlannedSession).where(PlannedSession.user_id == user_id)
            )
        ).scalar_one()
    assert planned.status is SessionStatus.SKIPPED


@pytest.mark.integration
async def test_persist_skip_push_moves_to_next_day(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 9205)
    async with sessions() as session:
        session.add(
            PlannedSession(
                user_id=user_id,
                scheduled_date=dt.date(2026, 6, 10),
                split_label="pull",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()

    await _service(sessions).persist(
        9205,
        {"kind": "skip", "summary": "Skip today", "skip_date": "2026-06-10", "skip_mode": "push"},
    )

    async with sessions() as session:
        rows = (
            await session.execute(
                select(PlannedSession)
                .where(PlannedSession.user_id == user_id)
                .order_by(PlannedSession.scheduled_date)
            )
        ).scalars().all()
    assert len(rows) == 2
    assert rows[0].scheduled_date == dt.date(2026, 6, 10)
    assert rows[0].status is SessionStatus.SKIPPED
    # The workout was pushed to the next day with the same split.
    assert rows[1].scheduled_date == dt.date(2026, 6, 11)
    assert rows[1].split_label == "pull"
    assert rows[1].status is SessionStatus.PLANNED
