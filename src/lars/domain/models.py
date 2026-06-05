"""Validated domain value objects stored as JSON in Postgres.

Most entities are modeled directly by the ORM (see ``lars.persistence.models``).
This module holds the structured payloads that need their own schema — currently
the workout prescription that is persisted as ``generated_workouts.prescription``.
"""

from pydantic import BaseModel, Field


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
