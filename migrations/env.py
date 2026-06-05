"""Alembic environment — synchronous migrations using psycopg.

The application runs async, but migrations run synchronously against the same
psycopg3 driver. The database URL comes from the DATABASE_URL env var so that
running migrations does not require the full application settings.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import models so their tables register on Base.metadata for autogenerate.
from lars.persistence import models  # noqa: F401
from lars.persistence.db import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

DEFAULT_URL = "postgresql+psycopg://lars:lars@localhost:5433/lars"


def get_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = get_url()
    engine = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
