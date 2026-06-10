"""On-demand generation: find (or create) the next session and (re)generate it."""

from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.domain.enums import SessionStatus
from lars.persistence.models import PlannedSession
from lars.persistence.repositories import UserRepository
from lars.scheduler.clock import Clock
from lars.scheduler.service import SchedulingService
from lars.services.generation import WorkoutGenerator, format_prescription

_OPEN_STATES = [SessionStatus.PLANNED, SessionStatus.GENERATED]


class RegenerationService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        scheduler: SchedulingService,
        generator: WorkoutGenerator,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._scheduler = scheduler
        self._generator = generator
        self._clock = clock

    async def generate_next(self, telegram_id: int) -> str:
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return "Let's get you set up first — just say hi to start."
            user_id = user.id
            today = self._clock.now().astimezone(ZoneInfo(user.timezone)).date()
            planned = (
                await session.execute(
                    select(PlannedSession)
                    .where(
                        PlannedSession.user_id == user_id,
                        PlannedSession.scheduled_date >= today,
                        PlannedSession.status.in_(_OPEN_STATES),
                    )
                    .order_by(PlannedSession.scheduled_date.asc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            planned_id = planned.id if planned is not None else None

        # No upcoming session yet — try to create tomorrow's if it's a training day.
        if planned_id is None:
            created = await self._scheduler.generate_for_tomorrow(user_id)
            planned_id = created.id if created is not None else None
        if planned_id is None:
            return "No training day coming up right now — enjoy the rest. Want to add one?"

        # allow_regenerate so an existing prescription is replaced on request.
        result = await self._generator.generate(planned_id, allow_regenerate=True)
        if result is None:
            return "I couldn't put that together just now — try again in a moment."
        return format_prescription(result.prescription)
