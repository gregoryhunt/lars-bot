"""Telegram application bootstrap."""

import logging
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from lars.adapters.llm.anthropic import AnthropicAdapter
from lars.config import Settings, get_settings
from lars.logging_config import setup_logging
from lars.persistence import create_engine, create_sessionmaker
from lars.prompts import PromptRegistry
from lars.scheduler.clock import SystemClock
from lars.scheduler.jobs import (
    GENERATOR_KEY,
    SCHEDULER_KEY,
    SESSIONMAKER_KEY,
    rehydrate_jobs,
)
from lars.scheduler.service import SchedulingService
from lars.services.generation import WorkoutGenerator
from lars.services.onboarding import DbOnboardingPersister
from lars.services.screenshots import DbScreenshotPersister, ScreenshotExtractor
from lars.telegram.handlers import (
    EXTRACTOR_KEY,
    GRAPH_KEY,
    SETTINGS_KEY,
    handle_callback,
    handle_photo,
    handle_text,
)
from lars.workflow import DbContextLoader, build_graph
from lars.workflow.checkpointer import to_libpq_url

logger = logging.getLogger(__name__)

_SAVER_CM_KEY = "_saver_cm"
_ENGINE_KEY = "_engine"


async def _post_init(app: Application) -> None:
    """Open the Postgres checkpointer and build the graph once the loop is running."""
    settings: Settings = app.bot_data[SETTINGS_KEY]
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)

    saver_cm = AsyncPostgresSaver.from_conn_string(to_libpq_url(settings.database_url))
    saver = await saver_cm.__aenter__()
    await saver.setup()

    adapter = AnthropicAdapter(settings.anthropic_api_key, settings.anthropic_model)
    registry = PromptRegistry()
    graph = build_graph(
        adapter,
        registry,
        saver,
        DbContextLoader(sessionmaker),
        onboarding_persister=DbOnboardingPersister(sessionmaker),
        screenshot_persister=DbScreenshotPersister(sessionmaker),
    )
    app.bot_data[GRAPH_KEY] = graph
    app.bot_data[EXTRACTOR_KEY] = ScreenshotExtractor(adapter, registry)
    clock = SystemClock()
    app.bot_data[SESSIONMAKER_KEY] = sessionmaker
    app.bot_data[SCHEDULER_KEY] = SchedulingService(sessionmaker, clock)
    app.bot_data[GENERATOR_KEY] = WorkoutGenerator(sessionmaker, adapter, registry, clock)
    app.bot_data[_SAVER_CM_KEY] = saver_cm
    app.bot_data[_ENGINE_KEY] = engine

    await rehydrate_jobs(app)
    logger.info("workflow graph ready")


async def _post_shutdown(app: Application) -> None:
    saver_cm: Any = app.bot_data.get(_SAVER_CM_KEY)
    if saver_cm is not None:
        await saver_cm.__aexit__(None, None, None)
    engine = app.bot_data.get(_ENGINE_KEY)
    if engine is not None:
        await engine.dispose()


def build_application(settings: Settings) -> Application:
    """Build the python-telegram-bot Application with handlers registered."""
    app = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    app.bot_data[SETTINGS_KEY] = settings

    # Photos first (more specific), then any text (including /commands), then taps.
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT, handle_text))
    app.add_handler(CallbackQueryHandler(handle_callback))
    return app


def run() -> None:
    """Entry point: configure logging, build the app, and poll for updates."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("starting Lars bot")
    app = build_application(settings)
    app.run_polling()
