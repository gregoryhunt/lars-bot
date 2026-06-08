"""Health metrics: BMI, BMR, TDEE, and a goal-based calorie target.

Wraps the healthsciencecalculator package, pulling inputs from the user's profile
and their most recent body-weight reading.
"""

import uuid
from dataclasses import dataclass

from healthsciencecalculator.get_bmi import get_bmi
from healthsciencecalculator.get_bmr import get_bmr
from healthsciencecalculator.get_tdee import get_tdee
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from lars.domain.enums import GoalType
from lars.persistence.models import BodyMetric, User

# Calorie adjustment vs maintenance (TDEE) by goal.
_GOAL_ADJUSTMENT = {
    GoalType.CUT: -500.0,
    GoalType.BULK: 300.0,
    GoalType.RECOMP: 0.0,
    GoalType.MAINTAIN: 0.0,
}


@dataclass(frozen=True)
class HealthMetrics:
    bmi: float
    bmi_category: str
    bmr: float
    tdee: float
    calorie_target: float


class HealthMetricsService:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def for_user(self, user_id: uuid.UUID) -> HealthMetrics | None:
        """Compute metrics, or None if the profile/weight inputs aren't available."""
        async with self._sessionmaker() as session:
            user = (
                await session.execute(
                    select(User)
                    .where(User.id == user_id)
                    .options(selectinload(User.profile), selectinload(User.goals))
                )
            ).scalar_one_or_none()
            if user is None or user.profile is None:
                return None
            profile = user.profile
            if (
                profile.age is None
                or profile.height_cm is None
                or profile.activity_level is None
                or not profile.sex
            ):
                return None

            weight_kg = (
                await session.execute(
                    select(BodyMetric.weight_kg)
                    .where(BodyMetric.user_id == user_id)
                    .order_by(BodyMetric.measured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if weight_kg is None:
                return None

            weight = float(weight_kg)
            height_cm = float(profile.height_cm)
            sex = "female" if profile.sex.lower().startswith("f") else "male"

            bmi_result = get_bmi(weight, height_cm / 100)
            bmr = get_bmr(weight, height_cm, profile.age, sex)
            tdee = get_tdee(bmr, profile.activity_level.value)
            adjustment = _GOAL_ADJUSTMENT.get(user.goals[0].type, 0.0) if user.goals else 0.0

            return HealthMetrics(
                bmi=bmi_result.bmi,
                bmi_category=bmi_result.category,
                bmr=bmr,
                tdee=tdee,
                calorie_target=tdee + adjustment,
            )
