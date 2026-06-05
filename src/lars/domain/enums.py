"""Shared enumerations used across the domain, ORM, and Pydantic models."""

from enum import StrEnum


class UserStatus(StrEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    PAUSED = "paused"


class ExperienceLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class GoalType(StrEnum):
    CUT = "cut"
    BULK = "bulk"
    MAINTAIN = "maintain"
    RECOMP = "recomp"


class SessionStatus(StrEnum):
    PLANNED = "planned"
    GENERATED = "generated"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    MISSED = "missed"


class CompletionSource(StrEnum):
    APPLE_FITNESS_SCREENSHOT = "apple_fitness_screenshot"
    MANUAL = "manual"
    OTHER = "other"


class BodyMetricSource(StrEnum):
    SMART_SCALE_SCREENSHOT = "smart_scale_screenshot"
    MANUAL = "manual"


class NutritionSource(StrEnum):
    OPEN_FOOD_FACTS = "open_food_facts"
    LABEL_PHOTO = "label_photo"
    LLM_ESTIMATE = "llm_estimate"
    MANUAL = "manual"


class JobType(StrEnum):
    NIGHTLY_GENERATION = "nightly_generation"
    SKIP_CHECK = "skip_check"
    GOAL_REVIEW = "goal_review"


class Intent(StrEnum):
    """Natural-language intents the classifier routes to (see conversational-flows.md)."""

    ONBOARDING = "onboarding"
    LOG_WORKOUT = "log_workout"
    LOG_WEIGHT = "log_weight"
    LOG_NUTRITION = "log_nutrition"
    VIEW_PLAN = "view_plan"
    VIEW_TRENDS = "view_trends"
    CHANGE_SCHEDULE = "change_schedule"
    REPORT_SKIP = "report_skip"
    REQUEST_GENERATION = "request_generation"
    HELP = "help"
    UNKNOWN = "unknown"

    @classmethod
    def parse(cls, raw: str) -> "Intent":
        """Best-effort parse of a model's label; falls back to UNKNOWN."""
        token = raw.strip().lower().splitlines()[0].strip() if raw.strip() else ""
        try:
            return cls(token)
        except ValueError:
            return cls.UNKNOWN
