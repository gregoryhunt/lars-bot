"""JobQueue registration and rehydration.

The scheduled_jobs table is the source of truth; the in-memory JobQueue is a
runtime cache rebuilt from it on startup (and lazily when a user first acts).
"""

import logging
import uuid
from collections.abc import Sequence
from datetime import time
from typing import Any, cast
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes

from lars.domain.enums import JobType
from lars.persistence.models import Event
from lars.persistence.repositories import JobWithUser, ScheduledJobRepository
from lars.services.generation import format_prescription

logger = logging.getLogger(__name__)

SCHEDULER_KEY = "scheduler"
SESSIONMAKER_KEY = "sessionmaker"
GENERATOR_KEY = "generator"
SUMMARY_KEY = "summary"

_DEFAULT_TIME = time(20, 0)
_SUNDAY = (6,)  # python-telegram-bot run_daily: 0=Mon … 6=Sun


def _job_name(prefix: str, telegram_id: int) -> str:
    return f"{prefix}:{telegram_id}"


def _job_data(context: ContextTypes.DEFAULT_TYPE) -> dict[str, Any] | None:
    if context.job is None or context.job.data is None:
        return None
    return cast(dict[str, Any], context.job.data)


async def _nightly_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    service = context.application.bot_data[SCHEDULER_KEY]
    generator = context.application.bot_data[GENERATOR_KEY]
    data = _job_data(context)
    if data is None:
        return
    user_id = uuid.UUID(data["user_id"])
    planned = await service.generate_for_tomorrow(user_id)
    if planned is None:
        return
    try:
        result = await generator.generate(planned.id)
    except Exception:
        logger.exception("nightly generation failed for user %s", user_id)
        await _surface_failure(context, user_id, data["telegram_id"])
        return
    if result is not None:
        await context.bot.send_message(
            chat_id=data["telegram_id"], text=format_prescription(result.prescription)
        )


async def _surface_failure(
    context: ContextTypes.DEFAULT_TYPE, user_id: uuid.UUID, telegram_id: int
) -> None:
    sessionmaker = context.application.bot_data.get(SESSIONMAKER_KEY)
    if sessionmaker is not None:
        async with sessionmaker() as session:
            session.add(Event(user_id=user_id, event_type="nightly_gen_failed", payload={}))
            await session.commit()
    await context.bot.send_message(
        chat_id=telegram_id,
        text="I hit a snag building tomorrow's workout — I'll try again shortly.",
    )


async def _skip_check_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    service = context.application.bot_data[SCHEDULER_KEY]
    data = _job_data(context)
    if data is None:
        return
    flagged = await service.run_skip_check(uuid.UUID(data["user_id"]))
    for planned in flagged:
        await context.bot.send_message(
            chat_id=data["telegram_id"],
            text=(
                f"Looks like your {planned.split_label} workout didn't get logged. "
                "Everything OK, or did you skip it?"
            ),
        )


async def _review_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    summary = context.application.bot_data[SUMMARY_KEY]
    data = _job_data(context)
    if data is None:
        return
    # The recurring check-in: weekly (light) most weeks, block (deep) every ~4-6.
    text = await summary.scheduled_review(data["telegram_id"])
    await context.bot.send_message(chat_id=data["telegram_id"], text=text)


# job_type -> (name prefix, callback, days-of-week or None for every day)
_CALLBACKS = {
    JobType.NIGHTLY_GENERATION: ("nightly", _nightly_job, None),
    JobType.SKIP_CHECK: ("skip", _skip_check_job, None),
    JobType.WEEKLY_SUMMARY: ("summary", _review_job, _SUNDAY),
}


def register_jobs(job_queue: Any, entries: Sequence[JobWithUser]) -> None:
    """(Re)register run_daily jobs for the given store rows, deduping by name."""
    for job, telegram_id, timezone in entries:
        callback = _CALLBACKS.get(job.job_type)
        if callback is None:
            continue
        prefix, fn, days = callback
        name = _job_name(prefix, telegram_id)
        for existing in job_queue.get_jobs_by_name(name):
            existing.schedule_removal()
        run_at = (job.run_local_time or _DEFAULT_TIME).replace(tzinfo=ZoneInfo(timezone))
        kwargs: dict[str, Any] = {
            "time": run_at,
            "name": name,
            "data": {"user_id": str(job.user_id), "telegram_id": telegram_id},
        }
        if days is not None:
            kwargs["days"] = days
        job_queue.run_daily(fn, **kwargs)


async def rehydrate_jobs(app: Application) -> None:
    sessionmaker = app.bot_data[SESSIONMAKER_KEY]
    async with sessionmaker() as session:
        entries = await ScheduledJobRepository(session).list_active()
    if app.job_queue is not None:
        register_jobs(app.job_queue, entries)
    logger.info("rehydrated %d scheduled jobs", len(entries))


async def ensure_user_jobs(app: Application, telegram_id: int) -> None:
    """Register a user's jobs into the live JobQueue if not already present."""
    job_queue = app.job_queue
    if job_queue is None or job_queue.get_jobs_by_name(_job_name("nightly", telegram_id)):
        return
    sessionmaker = app.bot_data[SESSIONMAKER_KEY]
    async with sessionmaker() as session:
        entries = await ScheduledJobRepository(session).list_for_telegram_id(telegram_id)
    register_jobs(job_queue, entries)
