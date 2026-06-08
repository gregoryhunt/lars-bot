"""Integration: health metrics compute from profile + latest weight, or return None."""

import datetime as dt
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import ActivityLevel, BodyMetricSource, GoalType
from lars.persistence.models import BodyMetric, Goal, Profile, User
from lars.services.metrics import HealthMetricsService


async def _make_user(
    sessions: async_sessionmaker[AsyncSession],
    telegram_id: int,
    *,
    with_profile: bool = True,
    with_weight: bool = True,
) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        if with_profile:
            user.profile = Profile(
                age=34,
                sex="male",
                height_cm=180,
                activity_level=ActivityLevel.MODERATELY_ACTIVE,
            )
            user.goals = [Goal(type=GoalType.CUT, is_active=True)]
        session.add(user)
        await session.flush()
        if with_weight:
            session.add(
                BodyMetric(
                    user_id=user.id,
                    measured_at=dt.datetime(2026, 6, 8, 7, 0, tzinfo=dt.UTC),
                    weight_kg=82.0,
                    source=BodyMetricSource.MANUAL,
                )
            )
        user_id = user.id
        await session.commit()
    return user_id


@pytest.mark.integration
async def test_metrics_compute_for_complete_profile(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 8501)
    metrics = await HealthMetricsService(sessions).for_user(user_id)

    assert metrics is not None
    # Harris-Benedict for 82kg / 180cm / 34 / male (~1858).
    assert 1850 < metrics.bmr < 1865
    # "moderately active" multiplier is 1.55; cut goal subtracts 500.
    assert round(metrics.tdee) == round(metrics.bmr * 1.55)
    assert metrics.calorie_target == metrics.tdee - 500
    assert metrics.bmi_category != ""


@pytest.mark.integration
async def test_metrics_none_without_weight(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 8502, with_weight=False)
    assert await HealthMetricsService(sessions).for_user(user_id) is None
