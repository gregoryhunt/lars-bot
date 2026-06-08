"""Derive a user's effective activity level from logged + reported activity.

TDEE's activity multiplier is meant to include exercise, so we infer the level
from completed workouts in the last week, bumped up by any untracked activity
(walks, yardwork) the user reports via the daily follow-up.
"""

from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import ActivityLevel
from lars.persistence.models import Event, WorkoutCompletion
from lars.persistence.repositories import UserRepository
from lars.scheduler.clock import Clock

_UNTRACKED_EVENT = "untracked_activity"

# Activity levels ordered from least to most active.
_TIERS = [
    ActivityLevel.SEDENTARY,
    ActivityLevel.LIGHTLY_ACTIVE,
    ActivityLevel.MODERATELY_ACTIVE,
    ActivityLevel.VERY_ACTIVE,
    ActivityLevel.EXTRA_ACTIVE,
]
# Lowest tier index implied by reported untracked activity.
_UNTRACKED_TIER = {"none": 0, "light": 1, "moderate": 2, "heavy": 3}


def _workout_tier(workouts_last_7: int) -> int:
    if workouts_last_7 <= 0:
        return 0
    if workouts_last_7 <= 2:
        return 1
    if workouts_last_7 <= 4:
        return 2
    if workouts_last_7 <= 6:
        return 3
    return 4


def derive_level(workouts_last_7: int, untracked_label: str | None) -> ActivityLevel:
    """Combine weekly workout count with reported untracked activity into a level."""
    index = max(_workout_tier(workouts_last_7), _UNTRACKED_TIER.get(untracked_label or "none", 0))
    return _TIERS[min(index, len(_TIERS) - 1)]


def _max_untracked(labels: list[str | None]) -> str | None:
    best: str | None = None
    best_tier = -1
    for label in labels:
        tier = _UNTRACKED_TIER.get(label or "", -1)
        if tier > best_tier:
            best, best_tier = label, tier
    return best


class ActivityService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    async def record_untracked(self, telegram_id: int, level: str) -> None:
        """Record reported untracked activity for the prior day."""
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return
            yesterday = (
                self._clock.now().astimezone(ZoneInfo(user.timezone)).date() - timedelta(days=1)
            )
            session.add(
                Event(
                    user_id=user.id,
                    event_type=_UNTRACKED_EVENT,
                    payload={"level": level, "date": yesterday.isoformat()},
                )
            )
            await session.commit()

    async def refresh_profile(self, telegram_id: int) -> ActivityLevel | None:
        """Recompute the effective activity level from the last week and persist it."""
        cutoff = self._clock.now() - timedelta(days=7)
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None or user.profile is None:
                return None
            workouts = (
                await session.execute(
                    select(func.count())
                    .select_from(WorkoutCompletion)
                    .where(
                        WorkoutCompletion.user_id == user.id,
                        WorkoutCompletion.performed_at >= cutoff,
                    )
                )
            ).scalar_one()
            payloads = (
                await session.execute(
                    select(Event.payload).where(
                        Event.user_id == user.id,
                        Event.event_type == _UNTRACKED_EVENT,
                        Event.created_at >= cutoff,
                    )
                )
            ).scalars().all()
            untracked = _max_untracked([(p or {}).get("level") for p in payloads])

            level = derive_level(int(workouts), untracked)
            if user.profile.activity_level != level:
                user.profile.activity_level = level
                await session.commit()
            return level
