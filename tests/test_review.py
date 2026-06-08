"""Integration: the adaptive scheduled review (block-first, then weekly until due)."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import ActivityLevel, GoalType
from lars.persistence.models import Goal, Profile, User
from lars.prompts import PromptRegistry
from lars.services.metrics import HealthMetricsService
from lars.services.summary import SummaryService

pytestmark = pytest.mark.integration

_NOW = dt.datetime(2026, 6, 8, 16, 0, tzinfo=dt.UTC)


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


def _service(sessions: async_sessionmaker[AsyncSession], responses: list[str]) -> SummaryService:
    return SummaryService(
        sessions,
        MockModelAdapter(responses, default="ok"),
        PromptRegistry(),
        HealthMetricsService(sessions),
        FixedClock(_NOW),
    )


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> None:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        user.profile = Profile(
            age=34, sex="male", height_cm=180, activity_level=ActivityLevel.MODERATELY_ACTIVE
        )
        user.goals = [Goal(type=GoalType.CUT, is_active=True)]
        session.add(user)
        await session.commit()


async def _next_review_on(
    sessions: async_sessionmaker[AsyncSession], telegram_id: int
) -> dt.date | None:
    async with sessions() as session:
        return (
            await session.execute(
                select(User.next_block_review_on).where(User.telegram_id == telegram_id)
            )
        ).scalar_one()


async def test_first_review_is_block_and_schedules_next(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _make_user(sessions, 8801)
    # No prior review date -> a block review is due now.
    assert await _next_review_on(sessions, 8801) is None

    await _service(sessions, ["here's your level-set"]).scheduled_review(8801)

    next_on = await _next_review_on(sessions, 8801)
    today = _NOW.astimezone(ZoneInfo("America/New_York")).date()
    assert next_on is not None
    # Lars scheduled the next block review 4-6 weeks out.
    assert dt.timedelta(weeks=4) <= (next_on - today) <= dt.timedelta(weeks=6)


async def test_review_is_weekly_until_block_is_due(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _make_user(sessions, 8802)
    # Force a future block date so the next review is the light weekly one.
    future = _NOW.date() + dt.timedelta(weeks=3)
    async with sessions() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == 8802))
        ).scalar_one()
        user.next_block_review_on = future
        await session.commit()

    await _service(sessions, ["light weekly check-in"]).scheduled_review(8802)

    # Weekly reviews must not move the block date.
    assert await _next_review_on(sessions, 8802) == future
