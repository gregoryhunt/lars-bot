"""Persist a completed onboarding result into Postgres."""

from datetime import UTC, datetime, time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import BodyMetricSource, JobType, UserStatus
from lars.domain.models import OnboardingResult
from lars.persistence.models import (
    BodyMetric,
    Event,
    Goal,
    Profile,
    User,
    WorkoutSchedule,
)
from lars.persistence.repositories import ScheduledJobRepository, UserRepository

_SKIP_CHECK_TIME = time(21, 0)
_SUMMARY_TIME = time(18, 0)
_ACTIVITY_CHECK_TIME = time(9, 0)


def _parse_hhmm(value: str) -> time:
    hour, _, minute = value.partition(":")
    return time(int(hour), int(minute or 0))


class DbOnboardingPersister:
    """Writes the user, profile, goal, and schedule, and marks the user active."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def __call__(self, telegram_id: int, result: OnboardingResult) -> None:
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                user = User(telegram_id=telegram_id)
                session.add(user)

            generation_time = _parse_hhmm(result.generation_local_time)
            user.display_name = result.display_name
            user.timezone = result.timezone
            user.unit_system = result.unit_system
            user.status = UserStatus.ACTIVE
            user.profile = Profile(
                age=result.age,
                sex=result.sex,
                height_cm=result.height_cm,
                experience_level=result.experience_level,
                activity_level=result.activity_level,
                equipment_access={"items": result.equipment_access},
            )
            if result.weight_kg is not None:
                user.body_metrics = [
                    BodyMetric(
                        measured_at=datetime.now(UTC),
                        weight_kg=result.weight_kg,
                        source=BodyMetricSource.MANUAL,
                    )
                ]
            user.goals = [
                Goal(
                    type=result.goal_type,
                    target_weight_kg=result.target_weight_kg,
                    is_active=True,
                )
            ]
            user.schedules = [
                WorkoutSchedule(
                    definition=result.schedule,
                    generation_local_time=generation_time,
                    effective_from=datetime.now(UTC).date(),
                    is_active=True,
                )
            ]
            await session.flush()

            jobs = ScheduledJobRepository(session)
            await jobs.ensure(user.id, JobType.NIGHTLY_GENERATION, generation_time)
            await jobs.ensure(user.id, JobType.SKIP_CHECK, _SKIP_CHECK_TIME)
            await jobs.ensure(user.id, JobType.WEEKLY_SUMMARY, _SUMMARY_TIME)
            await jobs.ensure(user.id, JobType.ACTIVITY_CHECK, _ACTIVITY_CHECK_TIME)

            session.add(
                Event(
                    user_id=user.id,
                    event_type="onboarding_completed",
                    payload={"display_name": result.display_name},
                )
            )
            await session.commit()
