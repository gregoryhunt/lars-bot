"""Body-metrics repository (weight + body composition)."""

import uuid
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lars.persistence.models import BodyMetric


class BodyMetricRepositoryProtocol(Protocol):
    async def add(self, metric: BodyMetric) -> BodyMetric: ...
    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[BodyMetric]: ...


class BodyMetricRepository:
    """Reads and writes body-metric records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, metric: BodyMetric) -> BodyMetric:
        self._session.add(metric)
        await self._session.flush()
        return metric

    async def list_for_user(self, user_id: uuid.UUID) -> Sequence[BodyMetric]:
        stmt = (
            select(BodyMetric)
            .where(BodyMetric.user_id == user_id)
            .order_by(BodyMetric.measured_at.desc())
        )
        result = await self._session.execute(stmt)
        return result.scalars().all()
