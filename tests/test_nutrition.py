"""Integration: nutrition logging via LLM estimate and Open Food Facts, with totals."""

import datetime as dt
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import NutritionSource
from lars.domain.models import NutritionFacts
from lars.persistence.models import NutritionLog, User
from lars.persistence.repositories import NutritionRepository
from lars.prompts import PromptRegistry
from lars.services.nutrition import NutritionService

pytestmark = pytest.mark.integration

NUTRITION_JSON = (
    '{"items": [{"name": "banana", "quantity": "1 medium", '
    '"calories": 105, "protein_g": 1.3, "carbs_g": 27, "fat_g": 0.3}]}'
)


class FixedClock:
    def __init__(self, now: dt.datetime) -> None:
        self._now = now

    def now(self) -> dt.datetime:
        return self._now


class FakeLookup:
    def __init__(self, facts: NutritionFacts | None) -> None:
        self._facts = facts

    async def by_barcode(self, barcode: str) -> NutritionFacts | None:
        return self._facts


async def _make_user(sessions: async_sessionmaker[AsyncSession], telegram_id: int) -> uuid.UUID:
    async with sessions() as session:
        user = User(telegram_id=telegram_id, timezone="America/New_York")
        session.add(user)
        await session.flush()
        user_id = user.id
        await session.commit()
    return user_id


def _service(
    sessions: async_sessionmaker[AsyncSession],
    responses: list[str],
    lookup: FakeLookup | None = None,
) -> NutritionService:
    now = dt.datetime(2026, 6, 8, 16, 0, tzinfo=dt.UTC)
    return NutritionService(
        sessions, MockModelAdapter(responses), PromptRegistry(), lookup, FixedClock(now)
    )


async def test_text_meal_logged_as_estimate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 8001)
    reply = await _service(sessions, [NUTRITION_JSON]).log_from_text(8001, "ate a banana")

    assert "logged" in reply.lower()
    async with sessions() as session:
        rows = (
            await session.execute(select(NutritionLog).where(NutritionLog.user_id == user_id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source is NutritionSource.LLM_ESTIMATE
    assert rows[0].calories == 105


async def test_barcode_resolves_via_open_food_facts(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 8002)
    facts = NutritionFacts(
        name="Chobani", serving="150g", calories=140, protein_g=12, carbs_g=20, fat_g=2.5
    )
    service = _service(sessions, [], lookup=FakeLookup(facts))

    await service.log_from_text(8002, "3017620422003")

    async with sessions() as session:
        rows = (
            await session.execute(select(NutritionLog).where(NutritionLog.user_id == user_id))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].source is NutritionSource.OPEN_FOOD_FACTS
    assert rows[0].off_barcode == "3017620422003"
    assert rows[0].calories == 140


async def test_daily_totals_accumulate(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    user_id = await _make_user(sessions, 8003)
    service = _service(sessions, [NUTRITION_JSON, NUTRITION_JSON])

    await service.log_from_text(8003, "a banana")
    reply = await service.log_from_text(8003, "another banana")
    assert "210" in reply  # two bananas at 105 cal

    async with sessions() as session:
        rows = (
            await session.execute(select(NutritionLog).where(NutritionLog.user_id == user_id))
        ).scalars().all()
        totals = await NutritionRepository(session).daily_totals(user_id, rows[0].logged_for_date)
    assert round(totals.calories) == 210
