"""Activity-level derivation and the refresh-from-logged-activity service."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import ActivityLevel, CompletionSource
from lars.persistence.models import Profile, User, WorkoutCompletion
from lars.services.activity import ActivityService, derive_level

_NOW = dt.datetime(2026, 6, 8, 16, 0, tzinfo=dt.UTC)


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


def test_derive_level_from_workouts() -> None:
    assert derive_level(0, None) is ActivityLevel.SEDENTARY
    assert derive_level(2, None) is ActivityLevel.LIGHTLY_ACTIVE
    assert derive_level(4, None) is ActivityLevel.MODERATELY_ACTIVE
    assert derive_level(6, None) is ActivityLevel.VERY_ACTIVE
    assert derive_level(8, None) is ActivityLevel.EXTRA_ACTIVE


def test_untracked_activity_bumps_level() -> None:
    # Few workouts but heavy untracked activity lifts the level.
    assert derive_level(1, "heavy") is ActivityLevel.VERY_ACTIVE
    # ...but never below the workout-implied level.
    assert derive_level(6, "light") is ActivityLevel.VERY_ACTIVE


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> None:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        user.profile = Profile(activity_level=ActivityLevel.SEDENTARY)
        session.add(user)
        await session.flush()
        for day in (2, 3, 4):  # three completed workouts in the last week
            session.add(
                WorkoutCompletion(
                    user_id=user.id,
                    source=CompletionSource.APPLE_FITNESS_SCREENSHOT,
                    performed_at=dt.datetime(2026, 6, day, 18, tzinfo=dt.UTC),
                )
            )
        await session.commit()


async def _activity_level(
    sessions: async_sessionmaker[AsyncSession], telegram_id: int
) -> ActivityLevel | None:
    async with sessions() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one()
        profile = (
            await session.execute(select(Profile).where(Profile.user_id == user.id))
        ).scalar_one()
        return profile.activity_level


@pytest.mark.integration
async def test_refresh_updates_level_from_workouts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _make_user(sessions, 9101)
    level = await ActivityService(sessions, FixedClock(_NOW)).refresh_profile(9101)

    # 3 workouts/week -> moderately active (was sedentary at onboarding).
    assert level is ActivityLevel.MODERATELY_ACTIVE
    assert await _activity_level(sessions, 9101) is ActivityLevel.MODERATELY_ACTIVE


@pytest.mark.integration
async def test_reported_untracked_activity_raises_level(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _make_user(sessions, 9102)
    service = ActivityService(sessions, FixedClock(_NOW))

    await service.record_untracked(9102, "heavy")
    level = await service.refresh_profile(9102)

    # 3 workouts (moderately active) + heavy untracked -> very active.
    assert level is ActivityLevel.VERY_ACTIVE
