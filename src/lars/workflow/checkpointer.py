"""Checkpointer helpers for the workflow graph."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def to_libpq_url(database_url: str) -> str:
    """Convert a SQLAlchemy ``postgresql+psycopg://`` URL to a plain libpq URL."""
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@asynccontextmanager
async def postgres_checkpointer(database_url: str) -> AsyncIterator[Any]:
    """Yield a set-up AsyncPostgresSaver for the given database URL."""
    async with AsyncPostgresSaver.from_conn_string(to_libpq_url(database_url)) as saver:
        await saver.setup()
        yield saver
