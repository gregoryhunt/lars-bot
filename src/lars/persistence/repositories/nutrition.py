"""Nutrition log repository: write entries and compute daily totals."""

import uuid
from datetime import date
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lars.persistence.models import NutritionLog


class DailyTotals(NamedTuple):
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class NutritionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def add(self, entry: NutritionLog) -> NutritionLog:
        self._session.add(entry)
        return entry

    async def daily_totals(self, user_id: uuid.UUID, day: date) -> DailyTotals:
        zero = func.coalesce
        row = (
            await self._session.execute(
                select(
                    zero(func.sum(NutritionLog.calories), 0.0),
                    zero(func.sum(NutritionLog.protein_g), 0.0),
                    zero(func.sum(NutritionLog.carbs_g), 0.0),
                    zero(func.sum(NutritionLog.fat_g), 0.0),
                ).where(
                    NutritionLog.user_id == user_id,
                    NutritionLog.logged_for_date == day,
                )
            )
        ).one()
        return DailyTotals(float(row[0]), float(row[1]), float(row[2]), float(row[3]))
