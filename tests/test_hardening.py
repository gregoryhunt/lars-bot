"""Hardening: nightly-gen failure is surfaced + audited; the error handler is safe."""

import datetime as dt
import types
import uuid
from typing import Any
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.persistence.models import Event, User, WorkoutSchedule
from lars.scheduler.jobs import GENERATOR_KEY, SCHEDULER_KEY, SESSIONMAKER_KEY, _nightly_job
from lars.scheduler.service import SchedulingService
from lars.telegram.app import on_error

_WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


class RaisingGenerator:
    async def generate(self, planned_id: uuid.UUID, *, allow_regenerate: bool = False) -> Any:
        raise RuntimeError("LLM unavailable")


@pytest.mark.integration
async def test_nightly_failure_is_surfaced_and_audited(
    sessions: async_sessionmaker[AsyncSession], migrated_db: str
) -> None:
    now = dt.datetime(2026, 6, 8, 23, 0, tzinfo=dt.UTC)
    tomorrow = (now.astimezone(ZoneInfo("America/New_York")) + dt.timedelta(days=1)).date()
    async with sessions() as session:
        user = User(telegram_id=9001, timezone="America/New_York")
        session.add(user)
        await session.flush()
        user_id = user.id
        session.add(
            WorkoutSchedule(
                user_id=user_id,
                definition={_WEEKDAYS[tomorrow.weekday()]: "push"},
                generation_local_time=dt.time(20, 0),
                effective_from=dt.date(2026, 1, 1),
                is_active=True,
            )
        )
        await session.commit()

    bot = types.SimpleNamespace(send_message=AsyncMock())
    application = types.SimpleNamespace(
        bot_data={
            SCHEDULER_KEY: SchedulingService(sessions, FixedClock(now)),
            GENERATOR_KEY: RaisingGenerator(),
            SESSIONMAKER_KEY: sessions,
        }
    )
    job = types.SimpleNamespace(data={"user_id": str(user_id), "telegram_id": 9001})
    context = types.SimpleNamespace(application=application, job=job, bot=bot)

    await _nightly_job(context)  # ty: ignore[invalid-argument-type]

    bot.send_message.assert_awaited_once()
    assert "snag" in bot.send_message.call_args.kwargs["text"].lower()
    async with sessions() as session:
        events = (
            await session.execute(
                select(Event).where(
                    Event.user_id == user_id, Event.event_type == "nightly_gen_failed"
                )
            )
        ).scalars().all()
    assert len(events) == 1


async def test_error_handler_swallows_exceptions() -> None:
    context = types.SimpleNamespace(error=RuntimeError("kaboom"))
    # The global handler must never raise, so a failing update can't crash the bot.
    await on_error(object(), context)  # ty: ignore[invalid-argument-type]
