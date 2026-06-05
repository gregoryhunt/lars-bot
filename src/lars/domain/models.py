"""Validated domain value objects stored as JSON in Postgres.

Most entities are modeled directly by the ORM (see ``lars.persistence.models``).
This module holds the structured payloads that need their own schema — currently
the workout prescription that is persisted as ``generated_workouts.prescription``.
"""

from pydantic import BaseModel, Field

from lars.domain.enums import ExperienceLevel, GoalType


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
