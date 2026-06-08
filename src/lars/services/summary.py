"""Compile a period summary (workouts, weight, nutrition, metrics) and phrase it."""

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import ModelAdapter
from lars.domain.enums import SessionStatus
from lars.persistence.models import BodyMetric, NutritionLog, PlannedSession
from lars.persistence.repositories import UserRepository
from lars.prompts import PromptRegistry
from lars.scheduler.clock import Clock
from lars.services.metrics import HealthMetrics, HealthMetricsService

_NO_USER = "Let's get you set up first — just say hi to start."


@dataclass(frozen=True)
class SummaryStats:
    period_days: int
    workouts_completed: int
    workouts_skipped: int
    workouts_missed: int
    weight_latest: float | None
    weight_change: float | None
    avg_daily_calories: float | None
    metrics: HealthMetrics | None


def _fmt(value: float | None, unit: str, *, signed: bool = False) -> str:
    if value is None:
        return "n/a"
    number = f"{value:+.1f}" if signed else f"{value:.1f}"
    return f"{number} {unit}"


def _period_label(period_days: int) -> str:
    return {7: "week", 30: "month"}.get(period_days, f"{period_days} days")


class SummaryService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapter: ModelAdapter,
        registry: PromptRegistry,
        metrics_service: HealthMetricsService,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._adapter = adapter
        self._registry = registry
        self._metrics = metrics_service
        self._clock = clock

    async def build_stats(self, telegram_id: int, period_days: int) -> SummaryStats | None:
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return None
            user_id = user.id
            tz = ZoneInfo(user.timezone)
            today = self._clock.now().astimezone(tz).date()
            start = today - timedelta(days=period_days)

            status_rows = (
                await session.execute(
                    select(PlannedSession.status, func.count())
                    .where(
                        PlannedSession.user_id == user_id,
                        PlannedSession.scheduled_date >= start,
                        PlannedSession.scheduled_date <= today,
                    )
                    .group_by(PlannedSession.status)
                )
            ).all()
            counts = {status: count for status, count in status_rows}

            weight_rows = (
                await session.execute(
                    select(BodyMetric.measured_at, BodyMetric.weight_kg)
                    .where(BodyMetric.user_id == user_id)
                    .order_by(BodyMetric.measured_at.asc())
                )
            ).all()
            in_window = [float(w) for at, w in weight_rows if at.astimezone(tz).date() >= start]
            weight_latest = float(weight_rows[-1][1]) if weight_rows else None
            weight_change = in_window[-1] - in_window[0] if len(in_window) >= 2 else None

            total_cal, days_logged = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(NutritionLog.calories), 0.0),
                        func.count(func.distinct(NutritionLog.logged_for_date)),
                    ).where(
                        NutritionLog.user_id == user_id,
                        NutritionLog.logged_for_date >= start,
                        NutritionLog.logged_for_date <= today,
                    )
                )
            ).one()
            avg_daily = float(total_cal) / int(days_logged) if days_logged else None

        metrics = await self._metrics.for_user(user_id)
        return SummaryStats(
            period_days=period_days,
            workouts_completed=counts.get(SessionStatus.COMPLETED, 0),
            workouts_skipped=counts.get(SessionStatus.SKIPPED, 0),
            workouts_missed=counts.get(SessionStatus.MISSED, 0),
            weight_latest=weight_latest,
            weight_change=weight_change,
            avg_daily_calories=avg_daily,
            metrics=metrics,
        )

    async def summarize(self, telegram_id: int, period_days: int = 7) -> str:
        stats = await self.build_stats(telegram_id, period_days)
        if stats is None:
            return _NO_USER
        m = stats.metrics
        metrics_text = (
            f"BMI {m.bmi} ({m.bmi_category}), TDEE ~{round(m.tdee)} cal, "
            f"calorie target ~{round(m.calorie_target)} cal"
            if m is not None
            else "unknown"
        )
        prompt = self._registry.render(
            "summary",
            period=_period_label(period_days),
            completed=stats.workouts_completed,
            skipped=stats.workouts_skipped,
            missed=stats.workouts_missed,
            weight_latest=_fmt(stats.weight_latest, "kg"),
            weight_change=_fmt(stats.weight_change, "kg", signed=True),
            avg_calories=_fmt(stats.avg_daily_calories, "cal"),
            metrics=metrics_text,
        )
        return await self._adapter.generate(prompt)
