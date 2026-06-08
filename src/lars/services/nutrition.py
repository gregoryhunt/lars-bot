"""Log nutrition from free text via Open Food Facts (barcode) or an LLM estimate."""

import json
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import ModelAdapter
from lars.adapters.nutrition import NutritionLookup
from lars.domain.enums import NutritionSource
from lars.domain.models import NutritionEstimate, NutritionItem
from lars.persistence.models import NutritionLog
from lars.persistence.repositories import DailyTotals, NutritionRepository, UserRepository
from lars.prompts import PromptRegistry
from lars.scheduler.clock import Clock


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def _maybe_barcode(text: str) -> str | None:
    token = text.strip()
    return token if token.isdigit() and 8 <= len(token) <= 14 else None


def _round(value: float | None) -> int:
    return round(value) if value is not None else 0


class NutritionService:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        adapter: ModelAdapter,
        registry: PromptRegistry,
        lookup: NutritionLookup | None,
        clock: Clock,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._adapter = adapter
        self._registry = registry
        self._lookup = lookup
        self._clock = clock

    async def log_from_text(self, telegram_id: int, text: str) -> str:
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return "Let's get you set up first — just say hi to start."

            day = self._clock.now().astimezone(ZoneInfo(user.timezone)).date()
            entries = await self._resolve(text)
            repo = NutritionRepository(session)
            for entry in entries:
                entry.user_id = user.id
                entry.logged_for_date = day
                repo.add(entry)
            await session.flush()
            totals = await repo.daily_totals(user.id, day)
            await session.commit()

        return _summary(entries, totals)

    async def _resolve(self, text: str) -> list[NutritionLog]:
        barcode = _maybe_barcode(text)
        if barcode is not None and self._lookup is not None:
            facts = await self._lookup.by_barcode(barcode)
            if facts is not None:
                return [
                    NutritionLog(
                        item_name=facts.name,
                        source=NutritionSource.OPEN_FOOD_FACTS,
                        quantity=facts.serving or "1 serving",
                        calories=facts.calories,
                        protein_g=facts.protein_g,
                        carbs_g=facts.carbs_g,
                        fat_g=facts.fat_g,
                        off_barcode=barcode,
                    )
                ]
        return [_entry_from_item(item) for item in await self._estimate(text)]

    async def _estimate(self, text: str) -> list[NutritionItem]:
        raw = await self._adapter.generate(
            self._registry.render("nutrition_extraction", message=text)
        )
        return NutritionEstimate.model_validate(json.loads(_strip_fences(raw))).items


def _entry_from_item(item: NutritionItem) -> NutritionLog:
    return NutritionLog(
        item_name=item.name,
        source=NutritionSource.LLM_ESTIMATE,
        quantity=item.quantity,
        calories=item.calories,
        protein_g=item.protein_g,
        carbs_g=item.carbs_g,
        fat_g=item.fat_g,
    )


def _summary(entries: list[NutritionLog], totals: DailyTotals) -> str:
    if not entries:
        return "I couldn't make sense of that — could you describe what you ate?"
    logged = _round(sum(e.calories or 0 for e in entries))
    return (
        f"Logged {len(entries)} item(s) (~{logged} cal). "
        f"Today: {_round(totals.calories)} cal, {_round(totals.protein_g)}g protein, "
        f"{_round(totals.carbs_g)}g carbs, {_round(totals.fat_g)}g fat."
    )
