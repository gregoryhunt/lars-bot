"""Integration: nightly session planning, skip detection, and job-store idempotency."""

import datetime as dt
import uuid
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import JobType, SessionStatus
from lars.persistence.models import PlannedSession, ScheduledJob, User, WorkoutSchedule
from lars.persistence.repositories import ScheduledJobRepository
from lars.scheduler.service import SchedulingService

pytestmark = pytest.mark.integration

TZ = "America/New_York"
_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


async def _make_user(
    sessions: async_sessionmaker[AsyncSession],
    telegram_id: int,
    *,
    schedule_def: dict[str, str],
) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone=TZ)
        session.add(user)
        await session.flush()
        session.add(
            WorkoutSchedule(
                user_id=user.id,
                definition=schedule_def,
                generation_local_time=dt.time(20, 0),
                effective_from=dt.date(2026, 1, 1),
                is_active=True,
            )
        )
        await session.commit()
        return user.id


async def test_nightly_generation_creates_exactly_one_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = dt.datetime(2026, 6, 1, 23, 0, tzinfo=dt.UTC)  # evening, user-local
    tomorrow = (now.astimezone(ZoneInfo(TZ)) + dt.timedelta(days=1)).date()
    user_id = await _make_user(sessions, 6001, schedule_def={_WEEKDAYS[tomorrow.weekday()]: "push"})

    service = SchedulingService(sessions, FixedClock(now))
    first = await service.generate_for_tomorrow(user_id)
    await service.generate_for_tomorrow(user_id)  # idempotent

    assert first is not None
    async with sessions() as session:
        rows = (
            await session.execute(select(PlannedSession).where(PlannedSession.user_id == user_id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].scheduled_date == tomorrow
    assert rows[0].split_label == "push"


async def test_nightly_generation_skips_rest_day(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    now = dt.datetime(2026, 6, 1, 23, 0, tzinfo=dt.UTC)
    tomorrow = (now.astimezone(ZoneInfo(TZ)) + dt.timedelta(days=1)).date()
    rest_weekday = _WEEKDAYS[(tomorrow.weekday() + 1) % 7]  # not tomorrow
    user_id = await _make_user(sessions, 6011, schedule_def={rest_weekday: "legs"})

    result = await SchedulingService(sessions, FixedClock(now)).generate_for_tomorrow(user_id)
    assert result is None


async def test_skip_check_flags_unlogged_session(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 6002, schedule_def={"mon": "push"})
    async with sessions() as session:
        session.add(
            PlannedSession(
                user_id=user_id,
                scheduled_date=dt.date(2026, 6, 1),
                split_label="push",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()

    # June 2, 01:00 ET — past the June 1 21:00 + 3h grace deadline (00:00 June 2).
    now = dt.datetime(2026, 6, 2, 5, 0, tzinfo=dt.UTC)
    flagged = await SchedulingService(sessions, FixedClock(now)).run_skip_check(user_id)

    assert len(flagged) == 1
    async with sessions() as session:
        planned = (
            await session.execute(select(PlannedSession).where(PlannedSession.user_id == user_id))
        ).scalar_one()
    assert planned.status is SessionStatus.MISSED


async def test_skip_check_respects_grace(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 6012, schedule_def={"mon": "push"})
    async with sessions() as session:
        session.add(
            PlannedSession(
                user_id=user_id,
                scheduled_date=dt.date(2026, 6, 1),
                split_label="push",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()

    # June 1, 22:00 ET — before the 00:00 deadline, so not yet flagged.
    now = dt.datetime(2026, 6, 2, 2, 0, tzinfo=dt.UTC)
    flagged = await SchedulingService(sessions, FixedClock(now)).run_skip_check(user_id)

    assert flagged == []
    async with sessions() as session:
        planned = (
            await session.execute(select(PlannedSession).where(PlannedSession.user_id == user_id))
        ).scalar_one()
    assert planned.status is SessionStatus.PLANNED


async def test_scheduled_job_ensure_is_idempotent(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        user = User(telegram_id=6003)
        session.add(user)
        await session.flush()
        repo = ScheduledJobRepository(session)
        await repo.ensure(user.id, JobType.NIGHTLY_GENERATION, dt.time(20, 0))
        await repo.ensure(user.id, JobType.NIGHTLY_GENERATION, dt.time(21, 30))
        await session.commit()
        rows = (
            await session.execute(select(ScheduledJob).where(ScheduledJob.user_id == user.id))
        ).scalars().all()

    assert len(rows) == 1
    assert rows[0].run_local_time == dt.time(21, 30)
