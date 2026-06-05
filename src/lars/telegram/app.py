"""Telegram application bootstrap."""

import logging

from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from lars.config import Settings, get_settings
from lars.logging_config import setup_logging
from lars.telegram.handlers import (
    SETTINGS_KEY,
    handle_callback,
    handle_photo,
    handle_text,
)

logger = logging.getLogger(__name__)


def build_application(settings: Settings) -> Application:
    """Build the python-telegram-bot Application with handlers registered."""
    app = Application.builder().token(settings.telegram_bot_token).build()
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
