"""Persist a post-workout pulse check."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.persistence.models import PulseCheck


class DbPulsePersister:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def __call__(
        self,
        completion_id: uuid.UUID,
        *,
        rpe: int | None,
        energy: int | None,
        soreness: int | None,
        note: str | None,
    ) -> None:
        async with self._sessionmaker() as session:
            session.add(
                PulseCheck(
                    completion_id=completion_id,
                    rpe=rpe,
                    energy=energy,
                    soreness=soreness,
                    note=note,
                    skipped=False,
                )
            )
            await session.commit()
