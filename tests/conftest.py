"""Shared test fixtures, including an integration Postgres harness.

Integration fixtures recreate a dedicated test database, apply Alembic
migrations, and hand back an async session factory. If Postgres is not
reachable, the dependent tests skip rather than fail.
"""

import os
from collections.abc import AsyncIterator

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.persistence import create_engine, create_sessionmaker

PG_HOST = os.environ.get("TEST_PG_HOST", "localhost")
PG_PORT = os.environ.get("TEST_PG_PORT", "5433")
PG_USER = os.environ.get("TEST_PG_USER", "lars")
PG_PASSWORD = os.environ.get("TEST_PG_PASSWORD", "lars")
TEST_DB = os.environ.get("TEST_PG_DB", "lars_test")


def _admin_dsn(dbname: str) -> str:
    return (
        f"host={PG_HOST} port={PG_PORT} user={PG_USER} "
        f"password={PG_PASSWORD} dbname={dbname}"
    )


def _sqlalchemy_url(dbname: str) -> str:
    return f"postgresql+psycopg://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{dbname}"


def _postgres_available() -> bool:
    try:
        with psycopg.connect(_admin_dsn("postgres"), connect_timeout=2):
            return True
    except Exception:
        return False


def _recreate_database() -> None:
    name = sql.Identifier(TEST_DB)
    with psycopg.connect(_admin_dsn("postgres"), autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))
        conn.execute(sql.SQL("CREATE DATABASE {}").format(name))


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """A freshly migrated test database; yields its SQLAlchemy URL."""
    if not _postgres_available():
        pytest.skip("Postgres not available")

    _recreate_database()
    url = _sqlalchemy_url(TEST_DB)

    cfg = Config("alembic.ini")
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous

    return url


@pytest.fixture
async def sessions(migrated_db: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """An async session factory bound to the migrated test database."""
    engine = create_engine(migrated_db)
    try:
        yield create_sessionmaker(engine)
    finally:
        await engine.dispose()
