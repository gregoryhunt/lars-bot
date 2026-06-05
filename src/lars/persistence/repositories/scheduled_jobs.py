"""Scheduled-job store: the durable source of truth rehydrated into the JobQueue."""

import uuid
from collections.abc import Sequence
from datetime import time
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lars.domain.enums import JobType
from lars.persistence.models import ScheduledJob, User


class JobWithUser(NamedTuple):
    job: ScheduledJob
    telegram_id: int
    timezone: str


class ScheduledJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ensure(
        self, user_id: uuid.UUID, job_type: JobType, run_local_time: time
    ) -> ScheduledJob:
        """Create or update the recurring job for (user, type); idempotent."""
        stmt = select(ScheduledJob).where(
            ScheduledJob.user_id == user_id,
            ScheduledJob.job_type == job_type,
            ScheduledJob.target_date.is_(None),
        )
        existing = (await self._session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            existing.run_local_time = run_local_time
            existing.is_active = True
            return existing
        job = ScheduledJob(
            user_id=user_id, job_type=job_type, run_local_time=run_local_time, is_active=True
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def list_active(self) -> Sequence[JobWithUser]:
        rows = (
            await self._session.execute(
                select(ScheduledJob, User.telegram_id, User.timezone)
                .join(User, ScheduledJob.user_id == User.id)
                .where(ScheduledJob.is_active.is_(True))
            )
        ).all()
        return [JobWithUser(job, telegram_id, tz) for job, telegram_id, tz in rows]

    async def list_for_telegram_id(self, telegram_id: int) -> Sequence[JobWithUser]:
        rows = (
            await self._session.execute(
                select(ScheduledJob, User.telegram_id, User.timezone)
                .join(User, ScheduledJob.user_id == User.id)
                .where(User.telegram_id == telegram_id, ScheduledJob.is_active.is_(True))
            )
        ).all()
        return [JobWithUser(job, tid, tz) for job, tid, tz in rows]
