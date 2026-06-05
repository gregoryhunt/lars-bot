"""Telegram handler tests: the allowlist gates every update.

These call the handler coroutines directly with stand-in Update/Context objects,
so no network or persistence is involved — which is also why "nothing is
persisted" for declined users holds: the decline path does no work beyond replying.
"""

import types
from typing import cast
from unittest.mock import AsyncMock

import pytest
from telegram import Update
from telegram.ext import ContextTypes

from lars.config import Settings
from lars.telegram.app import build_application
from lars.telegram.handlers import (
    DECLINE_MESSAGE,
    PHOTO_ACK,
    SETTINGS_KEY,
    TEXT_ACK,
    handle_callback,
    handle_photo,
    handle_text,
)

ALLOWED_ID = 111
BLOCKED_ID = 999


def make_context(allowlist: set[int]) -> ContextTypes.DEFAULT_TYPE:
    settings = types.SimpleNamespace(allowlist=frozenset(allowlist))
    ctx = types.SimpleNamespace(bot_data={SETTINGS_KEY: settings})
    return cast(ContextTypes.DEFAULT_TYPE, ctx)


def make_update(user_id: int) -> tuple[Update, AsyncMock]:
    reply = AsyncMock()
    message = types.SimpleNamespace(reply_text=reply)
    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=user_id),
        effective_message=message,
        callback_query=None,
    )
    return cast(Update, update), reply


async def test_allowlisted_text_is_acknowledged() -> None:
    update, reply = make_update(ALLOWED_ID)
    await handle_text(update, make_context({ALLOWED_ID}))
    reply.assert_awaited_once_with(TEXT_ACK)


async def test_non_allowlisted_text_is_declined() -> None:
    update, reply = make_update(BLOCKED_ID)
    await handle_text(update, make_context({ALLOWED_ID}))
    reply.assert_awaited_once_with(DECLINE_MESSAGE)


async def test_allowlisted_photo_is_acknowledged() -> None:
    update, reply = make_update(ALLOWED_ID)
    await handle_photo(update, make_context({ALLOWED_ID}))
    reply.assert_awaited_once_with(PHOTO_ACK)


async def test_callback_answers_and_declines_when_blocked() -> None:
    answer = AsyncMock()
    reply = AsyncMock()
    message = types.SimpleNamespace(reply_text=reply)
    update = cast(
        Update,
        types.SimpleNamespace(
            effective_user=types.SimpleNamespace(id=BLOCKED_ID),
            effective_message=message,
            callback_query=types.SimpleNamespace(answer=answer),
        ),
    )
    await handle_callback(update, make_context({ALLOWED_ID}))
    answer.assert_awaited_once()
    reply.assert_awaited_once_with(DECLINE_MESSAGE)


def test_build_application_registers_handlers() -> None:
    settings = cast(
        Settings,
        types.SimpleNamespace(telegram_bot_token="123:dummy", allowlist=frozenset({ALLOWED_ID})),
    )
    app = build_application(settings)

    assert app.bot_data[SETTINGS_KEY] is settings
    # Three handlers registered in the default group.
    assert len(app.handlers[0]) == 3


pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
