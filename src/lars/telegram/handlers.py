"""Telegram update handlers.

M2 is a skeleton: the allowlist gate runs first on every update; allowlisted
users get a placeholder acknowledgement, everyone else is politely declined.
Real intent handling arrives with the LangGraph workflow in M3+.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from lars.config import Settings

logger = logging.getLogger(__name__)

SETTINGS_KEY = "settings"

DECLINE_MESSAGE = (
    "Hi! I'm Lars, a private coaching bot, and I don't recognize this account, "
    "so I can't help here."
)
TEXT_ACK = "Got your message — I'm still being built, but I heard you. 👍"
PHOTO_ACK = "Got your photo — screenshot reading is coming soon. 📸"


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data[SETTINGS_KEY]


def is_allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """True if the update's sender is on the allowlist."""
    user = update.effective_user
    return user is not None and user.id in _settings(context).allowlist


async def _decline(update: Update) -> None:
    user = update.effective_user
    logger.info("declined non-allowlisted user %s", user.id if user else None)
    if update.effective_message is not None:
        await update.effective_message.reply_text(DECLINE_MESSAGE)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update, context):
        await _decline(update)
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(TEXT_ACK)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update, context):
        await _decline(update)
        return
    if update.effective_message is not None:
        await update.effective_message.reply_text(PHOTO_ACK)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None:
        await query.answer()
    if not is_allowed(update, context):
        await _decline(update)
