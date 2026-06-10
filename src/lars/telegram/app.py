"""Telegram application bootstrap."""

import logging
from typing import Any

import httpx
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from lars.adapters.llm import RetryingModelAdapter
from lars.adapters.llm.anthropic import AnthropicAdapter
from lars.adapters.nutrition import OpenFoodFactsClient
from lars.config import Settings, get_settings
from lars.logging_config import setup_logging
from lars.persistence import create_engine, create_sessionmaker
from lars.prompts import PromptRegistry
from lars.scheduler.clock import SystemClock
from lars.scheduler.jobs import (
    ACTIVITY_KEY,
    GENERATOR_KEY,
    SCHEDULER_KEY,
    SESSIONMAKER_KEY,
    SUMMARY_KEY,
    rehydrate_jobs,
)
from lars.scheduler.service import SchedulingService
from lars.services.activity import ActivityService
from lars.services.generation import WorkoutGenerator
from lars.services.metrics import HealthMetricsService
from lars.services.nutrition import NutritionService
from lars.services.onboarding import DbOnboardingPersister
from lars.services.pulse import DbPulsePersister
from lars.services.regeneration import RegenerationService
from lars.services.screenshots import DbScreenshotPersister, ScreenshotExtractor
from lars.services.summary import SummaryService
from lars.services.writes import WriteService
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
_HTTP_KEY = "_http"


async def _post_init(app: Application) -> None:
    """Open the Postgres checkpointer and build the graph once the loop is running."""
    settings: Settings = app.bot_data[SETTINGS_KEY]
    engine = create_engine(settings.database_url)
    sessionmaker = create_sessionmaker(engine)

    saver_cm = AsyncPostgresSaver.from_conn_string(to_libpq_url(settings.database_url))
    saver = await saver_cm.__aenter__()
    await saver.setup()

    adapter = RetryingModelAdapter(
        AnthropicAdapter(settings.anthropic_api_key, settings.anthropic_model)
    )
    registry = PromptRegistry()
    clock = SystemClock()
    http_client = httpx.AsyncClient(timeout=10.0)
    off_client = OpenFoodFactsClient(http_client)
    nutrition = NutritionService(sessionmaker, adapter, registry, off_client, clock)
    metrics_service = HealthMetricsService(sessionmaker)
    summary = SummaryService(sessionmaker, adapter, registry, metrics_service, clock)
    writes = WriteService(sessionmaker, adapter, registry, clock)
    scheduling = SchedulingService(sessionmaker, clock)
    generator = WorkoutGenerator(sessionmaker, adapter, registry, clock, metrics_service)
    regeneration = RegenerationService(sessionmaker, scheduling, generator, clock)
    graph = build_graph(
        adapter,
        registry,
        saver,
        DbContextLoader(sessionmaker),
        onboarding_persister=DbOnboardingPersister(sessionmaker),
        screenshot_persister=DbScreenshotPersister(sessionmaker),
        pulse_persister=DbPulsePersister(sessionmaker),
        nutrition_logger=nutrition,
        summary_provider=summary,
        write_provider=writes,
        regenerator=regeneration,
    )
    app.bot_data[GRAPH_KEY] = graph
    app.bot_data[EXTRACTOR_KEY] = ScreenshotExtractor(adapter, registry)
    app.bot_data[SESSIONMAKER_KEY] = sessionmaker
    app.bot_data[SCHEDULER_KEY] = scheduling
    app.bot_data[SUMMARY_KEY] = summary
    app.bot_data[ACTIVITY_KEY] = ActivityService(sessionmaker, clock)
    app.bot_data[GENERATOR_KEY] = generator
    app.bot_data[_SAVER_CM_KEY] = saver_cm
    app.bot_data[_ENGINE_KEY] = engine
    app.bot_data[_HTTP_KEY] = http_client

    await rehydrate_jobs(app)
    logger.info("workflow graph ready")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global handler so a single failed update can't crash the bot."""
    logger.exception("unhandled error while processing an update", exc_info=context.error)
    message = getattr(update, "effective_message", None) if isinstance(update, Update) else None
    if message is not None:
        try:
            await message.reply_text("Sorry — something went wrong on my end. Please try again.")
        except Exception:
            logger.exception("failed to notify the user about an error")


async def _post_shutdown(app: Application) -> None:
    saver_cm: Any = app.bot_data.get(_SAVER_CM_KEY)
    if saver_cm is not None:
        await saver_cm.__aexit__(None, None, None)
    http_client = app.bot_data.get(_HTTP_KEY)
    if http_client is not None:
        await http_client.aclose()
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
    app.add_error_handler(on_error)
    return app


def run() -> None:
    """Entry point: configure logging, build the app, and poll for updates."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("starting Lars bot")
    app = build_application(settings)
    app.run_polling()
