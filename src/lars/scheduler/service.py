"""Deterministic scheduling logic: plan tomorrow's session, detect skips.

Prescription generation (the LLM step) is M7; here the nightly job only ensures
the planned session exists. All time math is driven by an injected Clock so it is
testable, and is computed in each user's local timezone.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import SessionStatus
from lars.persistence.models import Event, PlannedSession, User, WorkoutSchedule
from lars.scheduler.clock import Clock

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class SchedulingService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._sessionmaker = sessionmaker
        self._clock = clock

    async def _active_schedule(
        self, session: AsyncSession, user_id: uuid.UUID
    ) -> WorkoutSchedule | None:
        return (
            await session.execute(
                select(WorkoutSchedule)
                .where(WorkoutSchedule.user_id == user_id, WorkoutSchedule.is_active.is_(True))
                .order_by(WorkoutSchedule.effective_from.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def generate_for_tomorrow(self, user_id: uuid.UUID) -> PlannedSession | None:
        """Ensure a planned session exists for the user's next (tomorrow) training day."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None:
                return None
            schedule = await self._active_schedule(session, user_id)
            if schedule is None:
                return None

            tz = ZoneInfo(user.timezone)
            tomorrow = (self._clock.now().astimezone(tz) + timedelta(days=1)).date()
            split = schedule.definition.get(_WEEKDAYS[tomorrow.weekday()])
            if not split:
                return None

            existing = (
                await session.execute(
                    select(PlannedSession).where(
                        PlannedSession.user_id == user_id,
                        PlannedSession.scheduled_date == tomorrow,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing

            planned = PlannedSession(
                user_id=user_id,
                scheduled_date=tomorrow,
                split_label=split,
                status=SessionStatus.PLANNED,
                source_schedule_id=schedule.id,
            )
            session.add(planned)
            await session.flush()
            session.add(
                Event(
                    user_id=user_id,
                    event_type="session_planned",
                    payload={"date": tomorrow.isoformat(), "split": split},
                )
            )
            await session.commit()
            return planned

    async def run_skip_check(self, user_id: uuid.UUID) -> Sequence[PlannedSession]:
        """Mark unlogged training days past their grace period as missed; return them."""
        async with self._sessionmaker() as session:
            user = await session.get(User, user_id)
            if user is None:
                return []
            schedule = await self._active_schedule(session, user_id)
            if schedule is None:
                return []

            tz = ZoneInfo(user.timezone)
            now_local = self._clock.now().astimezone(tz)
            today = now_local.date()

            candidates = (
                await session.execute(
                    select(PlannedSession).where(
                        PlannedSession.user_id == user_id,
                        PlannedSession.scheduled_date <= today,
                        PlannedSession.status.in_(
                            [SessionStatus.PLANNED, SessionStatus.GENERATED]
                        ),
                    )
                )
            ).scalars().all()

            flagged: list[PlannedSession] = []
            for planned in candidates:
                deadline = datetime.combine(
                    planned.scheduled_date, schedule.skip_check_local_time, tzinfo=tz
                ) + timedelta(hours=schedule.skip_check_grace_hours)
                if now_local >= deadline:
                    planned.status = SessionStatus.MISSED
                    session.add(
                        Event(
                            user_id=user_id,
                            event_type="session_missed",
                            payload={"date": planned.scheduled_date.isoformat()},
                        )
                    )
                    flagged.append(planned)
            await session.commit()
            return flagged
