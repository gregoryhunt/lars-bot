"""Telegram update handlers.

M2 is a skeleton: the allowlist gate runs first on every update; allowlisted
users get a placeholder acknowledgement, everyone else is politely declined.
Real intent handling arrives with the LangGraph workflow in M3+.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from lars.adapters.llm import Image
from lars.config import Settings
from lars.scheduler.jobs import ensure_user_jobs
from lars.services.screenshots import process_photo
from lars.workflow import run_turn
from lars.workflow.runner import TurnReply

logger = logging.getLogger(__name__)

SETTINGS_KEY = "settings"
GRAPH_KEY = "graph"
EXTRACTOR_KEY = "screenshot_extractor"

DECLINE_MESSAGE = (
    "Hi! I'm Lars, a private coaching bot, and I don't recognize this account, "
    "so I can't help here."
)
TEXT_ACK = "Got your message — I'm still being built, but I heard you. 👍"
PHOTO_ACK = "Got your photo — screenshot reading is coming soon. 📸"


def _settings(context: ContextTypes.DEFAULT_TYPE) -> Settings:
    return context.bot_data[SETTINGS_KEY]


def _markup(reply: TurnReply | str) -> InlineKeyboardMarkup | None:
    options = getattr(reply, "options", None)
    if not options:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(opt, callback_data=opt)] for opt in options])


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
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None:
        return
    graph = context.bot_data.get(GRAPH_KEY)
    if graph is None:
        # Graph not wired (e.g. a minimal app); fall back to a placeholder ack.
        await message.reply_text(TEXT_ACK)
        return
    config = {"configurable": {"thread_id": str(user.id)}}
    reply = await run_turn(graph, config, telegram_id=user.id, text=message.text or "")
    await message.reply_text(reply, reply_markup=_markup(reply))
    # A user who just finished onboarding becomes active; register their jobs.
    await ensure_user_jobs(context.application, user.id)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update, context):
        await _decline(update)
        return
    message = update.effective_message
    user = update.effective_user
    if message is None or user is None or not message.photo:
        return
    graph = context.bot_data.get(GRAPH_KEY)
    extractor = context.bot_data.get(EXTRACTOR_KEY)
    if graph is None or extractor is None:
        await message.reply_text(PHOTO_ACK)
        return
    photo_file = await message.photo[-1].get_file()
    data = await photo_file.download_as_bytearray()
    image = Image(bytes(data), "image/jpeg")
    config = {"configurable": {"thread_id": str(user.id)}}
    reply = await process_photo(extractor, graph, config, telegram_id=user.id, image=image)
    await message.reply_text(reply, reply_markup=_markup(reply))


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is not None:
        await query.answer()
    if not is_allowed(update, context):
        await _decline(update)
        return
    user = update.effective_user
    chat = update.effective_chat
    graph = context.bot_data.get(GRAPH_KEY)
    if graph is None or query is None or user is None or chat is None:
        return
    config = {"configurable": {"thread_id": str(user.id)}}
    reply = await run_turn(graph, config, telegram_id=user.id, text=query.data or "")
    await context.bot.send_message(
        chat_id=chat.id, text=reply or "👍", reply_markup=_markup(reply)
    )
