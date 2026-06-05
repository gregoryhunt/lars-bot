"""Integration tests: migrations apply and repositories round-trip on Postgres."""

import datetime as dt

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import BodyMetricSource, ExperienceLevel, GoalType, UserStatus
from lars.persistence.models import BodyMetric, Goal, Profile, User
from lars.persistence.repositories import BodyMetricRepository, UserRepository

pytestmark = pytest.mark.integration


async def test_user_aggregate_roundtrip(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        repo = UserRepository(session)
        user = User(
            telegram_id=12345,
            display_name="Greg",
            profile=Profile(
                age=34,
                sex="male",
                height_cm=180.3,
                experience_level=ExperienceLevel.INTERMEDIATE,
                equipment_access={"tags": ["barbell", "dumbbells"]},
            ),
            goals=[Goal(type=GoalType.CUT, target_weight_kg=80.0)],
        )
        await repo.add(user)
        await session.commit()
        user_id = user.id

    async with sessions() as session:
        repo = UserRepository(session)
        fetched = await repo.get_by_telegram_id(12345)

    assert fetched is not None
    assert fetched.id == user_id
    assert fetched.status is UserStatus.ONBOARDING  # column default applied
    assert fetched.timezone == "America/New_York"  # column default applied
    assert fetched.profile is not None
    assert fetched.profile.experience_level is ExperienceLevel.INTERMEDIATE
    assert fetched.profile.equipment_access == {"tags": ["barbell", "dumbbells"]}
    assert len(fetched.goals) == 1
    assert fetched.goals[0].type is GoalType.CUT
    assert fetched.goals[0].is_active is True  # column default applied


async def test_body_metric_roundtrip(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions() as session:
        user = User(telegram_id=222)
        session.add(user)
        await session.flush()

        repo = BodyMetricRepository(session)
        await repo.add(
            BodyMetric(
                user_id=user.id,
                measured_at=dt.datetime(2026, 6, 5, 7, 0, tzinfo=dt.UTC),
                weight_kg=82.4,
                body_fat_pct=17.2,
                source=BodyMetricSource.SMART_SCALE_SCREENSHOT,
            )
        )
        await session.commit()

        metrics = await repo.list_for_user(user.id)

    assert len(metrics) == 1
    assert float(metrics[0].weight_kg) == 82.4
    body_fat = metrics[0].body_fat_pct
    assert body_fat is not None
    assert float(body_fat) == 17.2
