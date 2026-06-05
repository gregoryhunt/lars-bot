"""User aggregate repository (user + profile + goals)."""

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from lars.persistence.models import User


class UserRepositoryProtocol(Protocol):
    async def add(self, user: User) -> User: ...
    async def get_by_telegram_id(self, telegram_id: int) -> User | None: ...


class UserRepository:
    """Reads and writes the user aggregate."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        stmt = (
            select(User)
            .where(User.telegram_id == telegram_id)
            .options(selectinload(User.profile), selectinload(User.goals))
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
