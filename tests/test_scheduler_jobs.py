"""Unit test: job registration dedups by name (so rehydration can't double-register)."""

import datetime as dt
import uuid
from typing import Any

from lars.domain.enums import JobType
from lars.persistence.models import ScheduledJob
from lars.persistence.repositories import JobWithUser
from lars.scheduler.jobs import register_jobs


class FakeJob:
    def __init__(self, name: str, queue: "FakeJobQueue") -> None:
        self.name = name
        self._queue = queue

    def schedule_removal(self) -> None:
        self._queue.jobs_list.remove(self)


class FakeJobQueue:
    def __init__(self) -> None:
        self.jobs_list: list[FakeJob] = []

    def get_jobs_by_name(self, name: str) -> list[FakeJob]:
        return [job for job in self.jobs_list if job.name == name]

    def run_daily(self, callback: Any, time: Any, name: str, data: Any) -> None:
        self.jobs_list.append(FakeJob(name, self))


def _entries(telegram_id: int) -> list[JobWithUser]:
    user_id = uuid.uuid4()
    nightly = ScheduledJob(
        user_id=user_id, job_type=JobType.NIGHTLY_GENERATION, run_local_time=dt.time(20, 0)
    )
    skip = ScheduledJob(
        user_id=user_id, job_type=JobType.SKIP_CHECK, run_local_time=dt.time(21, 0)
    )
    return [
        JobWithUser(nightly, telegram_id, "America/New_York"),
        JobWithUser(skip, telegram_id, "America/New_York"),
    ]


def test_register_jobs_dedups_on_reregistration() -> None:
    queue = FakeJobQueue()
    entries = _entries(999)

    register_jobs(queue, entries)
    register_jobs(queue, entries)  # simulates a restart / rehydrate

    assert len(queue.get_jobs_by_name("nightly:999")) == 1
    assert len(queue.get_jobs_by_name("skip:999")) == 1
    assert len(queue.jobs_list) == 2
