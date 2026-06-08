"""Integration: onboarding persists the user aggregate; re-messaging skips onboarding."""

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lars.adapters.llm import MockModelAdapter
from lars.domain.enums import ActivityLevel, ExperienceLevel, GoalType, UserStatus
from lars.persistence.repositories import BodyMetricRepository, UserRepository
from lars.prompts import PromptRegistry
from lars.services.onboarding import DbOnboardingPersister
from lars.workflow import DbContextLoader, build_graph, run_turn
from lars.workflow.checkpointer import postgres_checkpointer

pytestmark = pytest.mark.integration

TELEGRAM_ID = 4242

ONBOARDING_JSON = json.dumps(
    {
        "display_name": "Greg",
        "age": 34,
        "sex": "male",
        "height_cm": 180.3,
        "weight_kg": 82.0,
        "experience_level": "intermediate",
        "activity_level": "moderately active",
        "equipment_access": ["full gym"],
        "goal_type": "cut",
        "target_weight_kg": 80.0,
        "timezone": "America/New_York",
        "unit_system": "imperial",
        "schedule": {"mon": "push", "wed": "pull", "fri": "legs"},
        "generation_local_time": "20:00",
    }
)

ANSWERS = [
    "Greg",
    "34, male",
    "5'11\"",
    "180 lb",
    "moderately active",
    "lose fat",
    "intermediate",
    "push mon, pull wed, legs fri",
    "full gym",
    "US Eastern",
    "imperial",
]


async def _complete_onboarding(
    migrated_db: str, loader: DbContextLoader, persister: DbOnboardingPersister
) -> str:
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(
            MockModelAdapter([ONBOARDING_JSON]),
            PromptRegistry(),
            saver,
            loader,
            onboarding_persister=persister,
        )
        config: dict[str, Any] = {"configurable": {"thread_id": "ob-1"}}
        await run_turn(graph, config, telegram_id=TELEGRAM_ID, text="hi")
        reply = ""
        for answer in ANSWERS:
            reply = await run_turn(graph, config, telegram_id=TELEGRAM_ID, text=answer)
        return reply


async def test_onboarding_persists_and_then_routes_normally(
    sessions: async_sessionmaker[AsyncSession], migrated_db: str
) -> None:
    loader = DbContextLoader(sessions)
    persister = DbOnboardingPersister(sessions)

    reply = await _complete_onboarding(migrated_db, loader, persister)
    assert "all set" in reply.lower()

    # The user aggregate was persisted and marked active.
    async with sessions() as session:
        user = await UserRepository(session).get_by_telegram_id(TELEGRAM_ID)
        assert user is not None
        metrics = await BodyMetricRepository(session).list_for_user(user.id)
    assert user.status is UserStatus.ACTIVE
    assert user.timezone == "America/New_York"
    assert user.profile is not None
    assert user.profile.experience_level is ExperienceLevel.INTERMEDIATE
    assert user.profile.activity_level is ActivityLevel.MODERATELY_ACTIVE
    assert len(user.goals) == 1
    assert user.goals[0].type is GoalType.CUT
    # Onboarding's current weight became an initial body-metric reading.
    assert len(metrics) == 1
    assert float(metrics[0].weight_kg) == 82.0

    # No longer a new user, and a fresh turn routes to classify (not onboarding).
    assert await loader.is_new_user(TELEGRAM_ID) is False
    async with postgres_checkpointer(migrated_db) as saver:
        graph = build_graph(
            MockModelAdapter(["view_plan"]),
            PromptRegistry(),
            saver,
            loader,
            onboarding_persister=persister,
        )
        config: dict[str, Any] = {"configurable": {"thread_id": "ob-2"}}
        reply2 = await run_turn(graph, config, telegram_id=TELEGRAM_ID, text="what's today?")
    assert "plan" in reply2.lower()
