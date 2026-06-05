"""Integration: screenshots persist with the screenshot date and reconcile sessions."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import SessionStatus
from lars.domain.models import ScreenshotExtraction
from lars.persistence.models import PlannedSession, User, WorkoutCompletion
from lars.persistence.repositories import BodyMetricRepository
from lars.prompts import PromptRegistry
from lars.services.screenshots import DbScreenshotPersister
from lars.workflow import build_graph, run_turn
from lars.workflow.checkpointer import postgres_checkpointer
from lars.workflow.context import StubContextLoader

pytestmark = pytest.mark.integration


async def _confirm_screenshot(
    migrated_db: str,
    persister: DbScreenshotPersister,
    extraction: ScreenshotExtraction,
    thread_id: str,
    telegram_id: int,
) -> None:
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(
            MockModelAdapter([]),
            PromptRegistry(),
            saver,
            StubContextLoader(is_new=False),
            screenshot_persister=persister,
        )
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        await run_turn(
            graph, config, telegram_id=telegram_id, screenshot=extraction.model_dump(mode="json")
        )
        await run_turn(graph, config, telegram_id=telegram_id, text="yes")


async def test_body_metrics_saved_with_screenshot_date(
    sessions: async_sessionmaker[AsyncSession], migrated_db: str
) -> None:
    telegram_id = 5151
    async with sessions() as session:
        session.add(User(telegram_id=telegram_id))
        await session.commit()

    extraction = ScreenshotExtraction(
        kind="body_metrics",
        confidence=0.95,
        summary="181 lb on Jun 4",
        performed_at=dt.datetime(2026, 6, 4, 7, 0),
        weight_kg=82.1,
        body_fat_pct=17.5,
    )
    await _confirm_screenshot(
        migrated_db, DbScreenshotPersister(sessions), extraction, "shot-bm", telegram_id
    )

    async with sessions() as session:
        user = (
            await session.execute(select(User).where(User.telegram_id == telegram_id))
        ).scalar_one()
        metrics = await BodyMetricRepository(session).list_for_user(user.id)
    assert len(metrics) == 1
    assert float(metrics[0].weight_kg) == 82.1
    assert metrics[0].measured_at.date() == dt.date(2026, 6, 4)


async def test_workout_reconciles_to_planned_session(
    sessions: async_sessionmaker[AsyncSession], migrated_db: str
) -> None:
    telegram_id = 5252
    workout_date = dt.date(2026, 6, 4)
    async with sessions() as session:
        user = User(telegram_id=telegram_id)
        session.add(user)
        await session.flush()
        session.add(
            PlannedSession(
                user_id=user.id,
                scheduled_date=workout_date,
                split_label="pull",
                status=SessionStatus.PLANNED,
            )
        )
        await session.commit()
        user_id = user.id

    extraction = ScreenshotExtraction(
        kind="workout",
        confidence=0.9,
        summary="Strength training, 52 min on Jun 4",
        performed_at=dt.datetime(2026, 6, 4, 18, 0),
        workout_type="Traditional Strength Training",
        duration_min=52,
    )
    await _confirm_screenshot(
        migrated_db, DbScreenshotPersister(sessions), extraction, "shot-wk", telegram_id
    )

    async with sessions() as session:
        completion = (
            await session.execute(
                select(WorkoutCompletion).where(WorkoutCompletion.user_id == user_id)
            )
        ).scalar_one()
        planned = (
            await session.execute(
                select(PlannedSession).where(PlannedSession.user_id == user_id)
            )
        ).scalar_one()
    assert completion.planned_session_id == planned.id
    assert planned.status is SessionStatus.COMPLETED
    assert completion.performed_at.date() == workout_date
