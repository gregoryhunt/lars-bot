"""Vision extraction and persistence for workout / scale screenshots."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import Image, ModelAdapter
from lars.domain.enums import (
    BodyMetricSource,
    CompletionSource,
    NutritionSource,
    SessionStatus,
)
from lars.domain.models import ScreenshotExtraction
from lars.persistence.models import (
    BodyMetric,
    Event,
    NutritionLog,
    PlannedSession,
    WorkoutCompletion,
)
from lars.persistence.repositories import UserRepository
from lars.prompts import PromptRegistry
from lars.workflow.runner import run_turn

CONFIDENCE_THRESHOLD = 0.5

UNCLEAR_MESSAGE = (
    "I couldn't read that screenshot clearly. Could you resend a clearer photo of "
    "the full summary?"
)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class ScreenshotExtractor:
    """Runs the vision model over a screenshot and returns structured fields."""

    def __init__(self, adapter: ModelAdapter, registry: PromptRegistry) -> None:
        self._adapter = adapter
        self._registry = registry

    async def extract(self, image: Image) -> ScreenshotExtraction:
        prompt = self._registry.get("screenshot_extraction")
        raw = await self._adapter.generate_with_images(prompt, [image])
        return ScreenshotExtraction.model_validate(json.loads(_strip_fences(raw)))


def needs_clarification(extraction: ScreenshotExtraction) -> bool:
    """True when we should ask for a clearer photo rather than guess."""
    if extraction.kind == "unknown" or extraction.confidence < CONFIDENCE_THRESHOLD:
        return True
    if extraction.kind == "body_metrics":
        return extraction.weight_kg is None
    if extraction.kind == "workout":
        return extraction.workout_type is None and extraction.duration_min is None
    if extraction.kind == "nutrition_label":
        return extraction.calories is None
    return True


class DbScreenshotPersister:
    """Writes a body-metric or workout-completion record from an extraction."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def __call__(
        self, telegram_id: int, extraction: ScreenshotExtraction
    ) -> uuid.UUID | None:
        when = _aware(extraction.performed_at)
        raw = extraction.model_dump(mode="json")
        completion_id: uuid.UUID | None = None
        completion: WorkoutCompletion | None = None
        async with self._sessionmaker() as session:
            user = await UserRepository(session).get_by_telegram_id(telegram_id)
            if user is None:
                return None

            if extraction.kind == "body_metrics":
                session.add(
                    BodyMetric(
                        user_id=user.id,
                        measured_at=when,
                        weight_kg=extraction.weight_kg,
                        body_fat_pct=extraction.body_fat_pct,
                        lean_mass_kg=extraction.lean_mass_kg,
                        bmi=extraction.bmi,
                        source=BodyMetricSource.SMART_SCALE_SCREENSHOT,
                        raw_extracted=raw,
                    )
                )
                event_type = "weight_logged"
            elif extraction.kind == "nutrition_label":
                session.add(
                    NutritionLog(
                        user_id=user.id,
                        logged_for_date=when.date(),
                        item_name=extraction.item_name or "label",
                        source=NutritionSource.LABEL_PHOTO,
                        quantity="1 serving",
                        calories=extraction.calories,
                        protein_g=extraction.protein_g,
                        carbs_g=extraction.carbs_g,
                        fat_g=extraction.fat_g,
                        raw_extracted=raw,
                    )
                )
                event_type = "nutrition_logged"
            else:  # workout
                planned = (
                    await session.execute(
                        select(PlannedSession).where(
                            PlannedSession.user_id == user.id,
                            PlannedSession.scheduled_date == when.date(),
                        )
                    )
                ).scalar_one_or_none()
                completion = WorkoutCompletion(
                    user_id=user.id,
                    planned_session_id=planned.id if planned else None,
                    source=CompletionSource.APPLE_FITNESS_SCREENSHOT,
                    workout_type=extraction.workout_type,
                    duration_min=extraction.duration_min,
                    active_calories=extraction.active_calories,
                    avg_hr=extraction.avg_hr,
                    performed_at=when,
                    raw_extracted=raw,
                    confirmed_at=datetime.now(UTC),
                )
                session.add(completion)
                if planned is not None:
                    planned.status = SessionStatus.COMPLETED
                event_type = "workout_logged"

            await session.flush()
            if completion is not None:
                completion_id = completion.id
            session.add(
                Event(
                    user_id=user.id,
                    event_type=event_type,
                    payload={"summary": extraction.summary},
                )
            )
            await session.commit()
        return completion_id


async def process_photo(
    extractor: ScreenshotExtractor,
    graph: Any,
    config: dict[str, Any],
    *,
    telegram_id: int,
    image: Image,
) -> str:
    """Extract a screenshot; ask for a clearer photo, or run the confirm/persist turn."""
    extraction = await extractor.extract(image)
    if needs_clarification(extraction):
        return UNCLEAR_MESSAGE
    return await run_turn(
        graph, config, telegram_id=telegram_id, screenshot=extraction.model_dump(mode="json")
    )
