"""Validated domain value objects stored as JSON in Postgres.

Most entities are modeled directly by the ORM (see ``lars.persistence.models``).
This module holds the structured payloads that need their own schema — currently
the workout prescription that is persisted as ``generated_workouts.prescription``.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from lars.domain.enums import ExperienceLevel, GoalType


class ScreenshotExtraction(BaseModel):
    """What the vision model read from a workout, scale, or nutrition-label photo.

    The model classifies the screenshot, gives a confidence, a human-readable
    summary (in the original units), the date/time shown, and the structured
    fields in canonical units (kg).
    """

    kind: Literal["workout", "body_metrics", "nutrition_label", "unknown"] = "unknown"
    confidence: float = 0.0
    summary: str = ""
    performed_at: datetime | None = None  # the date/time shown on the screenshot

    # Workout (Apple Fitness summary)
    workout_type: str | None = None
    duration_min: float | None = None
    active_calories: float | None = None
    avg_hr: float | None = None

    # Body metrics (smart scale), canonical units
    weight_kg: float | None = None
    body_fat_pct: float | None = None
    lean_mass_kg: float | None = None
    bmi: float | None = None

    # Nutrition label (per serving)
    item_name: str | None = None
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class NutritionItem(BaseModel):
    """One logged food item with best-effort calories and macros."""

    name: str
    quantity: str | None = None
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class NutritionEstimate(BaseModel):
    """The model's estimate for a free-text meal description."""

    items: list[NutritionItem] = Field(default_factory=list)


class NutritionFacts(BaseModel):
    """Nutrition facts resolved from Open Food Facts (per serving or per 100g)."""

    name: str
    serving: str | None = None
    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None


class OnboardingResult(BaseModel):
    """Structured profile/goals/schedule extracted from the onboarding chat.

    The model performs unit conversion (heights to cm, weights to kg) and maps
    free text to the enums and IANA timezone; persistence then stores it as-is.
    """

    display_name: str
    age: int | None = None
    sex: str | None = None
    height_cm: float | None = None
    experience_level: ExperienceLevel | None = None
    equipment_access: list[str] = Field(default_factory=list)
    goal_type: GoalType
    target_weight_kg: float | None = None
    timezone: str = "America/New_York"
    unit_system: str = "imperial"
    schedule: dict[str, str] = Field(default_factory=dict)  # weekday -> split label
    generation_local_time: str = "20:00"


class PrescribedExercise(BaseModel):
    """One exercise in a generated workout prescription."""

    name: str
    sets: int | None = None
    reps: str | None = None  # free-form, e.g. "8-10" or "AMRAP"
    target_load: str | None = None  # e.g. "225 lb" or "bodyweight"
    target_duration_min: float | None = None  # for timed/cardio work
    notes: str | None = None


class WorkoutPrescription(BaseModel):
    """The night-before prescription for a planned session."""

    split_label: str
    exercises: list[PrescribedExercise] = Field(default_factory=list)
    session_notes: str | None = None
