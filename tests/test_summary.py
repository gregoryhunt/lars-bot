"""Summary service stats + rendering, and the view-trends conversational route."""

import datetime as dt
from typing import Any

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import (
    ActivityLevel,
    BodyMetricSource,
    GoalType,
    NutritionSource,
    SessionStatus,
)
from lars.persistence.models import (
    BodyMetric,
    Goal,
    NutritionLog,
    PlannedSession,
    Profile,
    User,
)
from lars.prompts import PromptRegistry
from lars.services.metrics import HealthMetricsService
from lars.services.summary import SummaryService
from lars.workflow import build_graph
from lars.workflow.context import StubContextLoader


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


_NOW = dt.datetime(2026, 6, 8, 16, 0, tzinfo=dt.UTC)  # afternoon ET on 2026-06-08


def _service(sessions: async_sessionmaker[AsyncSession], responses: list[str]) -> SummaryService:
    return SummaryService(
        sessions,
        MockModelAdapter(responses),
        PromptRegistry(),
        HealthMetricsService(sessions),
        FixedClock(_NOW),
    )


async def _seed(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> None:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        user.profile = Profile(
            age=34, sex="male", height_cm=180, activity_level=ActivityLevel.MODERATELY_ACTIVE
        )
        user.goals = [Goal(type=GoalType.CUT, is_active=True)]
        session.add(user)
        await session.flush()
        uid = user.id
        session.add_all(
            [
                PlannedSession(
                    user_id=uid,
                    scheduled_date=dt.date(2026, 6, 3),
                    split_label="push",
                    status=SessionStatus.COMPLETED,
                ),
                PlannedSession(
                    user_id=uid,
                    scheduled_date=dt.date(2026, 6, 5),
                    split_label="pull",
                    status=SessionStatus.SKIPPED,
                ),
                BodyMetric(
                    user_id=uid,
                    measured_at=dt.datetime(2026, 6, 2, 7, tzinfo=dt.UTC),
                    weight_kg=83.0,
                    source=BodyMetricSource.MANUAL,
                ),
                BodyMetric(
                    user_id=uid,
                    measured_at=dt.datetime(2026, 6, 7, 7, tzinfo=dt.UTC),
                    weight_kg=82.0,
                    source=BodyMetricSource.SMART_SCALE_SCREENSHOT,
                ),
                NutritionLog(
                    user_id=uid,
                    logged_for_date=dt.date(2026, 6, 6),
                    item_name="lunch",
                    source=NutritionSource.LLM_ESTIMATE,
                    calories=100,
                ),
                NutritionLog(
                    user_id=uid,
                    logged_for_date=dt.date(2026, 6, 7),
                    item_name="dinner",
                    source=NutritionSource.LLM_ESTIMATE,
                    calories=300,
                ),
            ]
        )
        await session.commit()


@pytest.mark.integration
async def test_build_stats_aggregates_window(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(sessions, 8701)
    stats = await _service(sessions, []).build_stats(8701, 7)

    assert stats is not None
    assert stats.workouts_completed == 1
    assert stats.workouts_skipped == 1
    assert stats.workouts_missed == 0
    assert stats.weight_latest == 82.0
    assert stats.weight_change == -1.0
    assert stats.avg_daily_calories == 200.0
    assert stats.metrics is not None  # profile + weight present


@pytest.mark.integration
async def test_summarize_renders_via_adapter(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    await _seed(sessions, 8702)
    reply = await _service(sessions, ["Solid week — nice work!"]).summarize(8702, 7)
    assert reply == "Solid week — nice work!"


@pytest.mark.integration
async def test_summarize_unknown_user(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    reply = await _service(sessions, ["unused"]).summarize(999999, 7)
    assert "set you up" in reply.lower() or "set up" in reply.lower()


class FakeSummary:
    def __init__(self) -> None:
        self.calls: list[tuple[int, int]] = []

    async def summarize(self, telegram_id: int, period_days: int = 7) -> str:
        self.calls.append((telegram_id, period_days))
        return f"summary:{period_days}d"


def _cfg(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


async def test_view_trends_routes_to_summary() -> None:
    fake = FakeSummary()
    graph = build_graph(
        MockModelAdapter(["view_trends"]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(),
        summary_provider=fake,
    )
    result = await graph.ainvoke({"telegram_id": 1, "text": "how's my week?"}, _cfg("sum1"))
    assert result["response"] == "summary:7d"
    assert fake.calls == [(1, 7)]


async def test_view_trends_month_uses_30_days() -> None:
    fake = FakeSummary()
    graph = build_graph(
        MockModelAdapter(["view_trends"]),
        PromptRegistry(),
        MemorySaver(),
        StubContextLoader(),
        summary_provider=fake,
    )
    await graph.ainvoke({"telegram_id": 1, "text": "how did my month go?"}, _cfg("sum2"))
    assert fake.calls == [(1, 30)]
