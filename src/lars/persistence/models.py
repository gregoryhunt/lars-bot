"""SQLAlchemy ORM models — the system of record. See docs/data-model.md."""

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from lars.domain.enums import (
    ActivityLevel,
    BodyMetricSource,
    CompletionSource,
    ExperienceLevel,
    GoalType,
    JobType,
    NutritionSource,
    SessionStatus,
    UserStatus,
)
from lars.persistence.db import Base, IdTimestampBase


class User(IdTimestampBase):
    __tablename__ = "users"

    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    unit_system: Mapped[str] = mapped_column(String(16), default="imperial")
    status: Mapped[UserStatus] = mapped_column(
        SAEnum(UserStatus, name="user_status"), default=UserStatus.ONBOARDING
    )

    profile: Mapped["Profile | None"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    goals: Mapped[list["Goal"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    schedules: Mapped[list["WorkoutSchedule"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    planned_sessions: Mapped[list["PlannedSession"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    body_metrics: Mapped[list["BodyMetric"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    nutrition_logs: Mapped[list["NutritionLog"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    scheduled_jobs: Mapped[list["ScheduledJob"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Profile(IdTimestampBase):
    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    age: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(32))
    height_cm: Mapped[float | None] = mapped_column(Numeric(5, 1))
    experience_level: Mapped[ExperienceLevel | None] = mapped_column(
        SAEnum(ExperienceLevel, name="experience_level")
    )
    activity_level: Mapped[ActivityLevel | None] = mapped_column(
        SAEnum(ActivityLevel, name="activity_level")
    )
    equipment_access: Mapped[dict | None] = mapped_column(JSONB)
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="profile")


class Goal(IdTimestampBase):
    __tablename__ = "goals"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[GoalType] = mapped_column(SAEnum(GoalType, name="goal_type"))
    target_weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2))
    target_date: Mapped[date | None] = mapped_column(Date)
    rationale: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="goals")


class WorkoutSchedule(IdTimestampBase):
    __tablename__ = "workout_schedules"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # weekday -> split label, e.g. {"mon": "push", "wed": "pull", "fri": "legs"}
    definition: Mapped[dict] = mapped_column(JSONB)
    generation_local_time: Mapped[time] = mapped_column(Time, default=time(20, 0))
    skip_check_local_time: Mapped[time] = mapped_column(Time, default=time(21, 0))
    skip_check_grace_hours: Mapped[int] = mapped_column(Integer, default=3)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    user: Mapped[User] = relationship(back_populates="schedules")


class PlannedSession(IdTimestampBase):
    __tablename__ = "planned_sessions"
    __table_args__ = (UniqueConstraint("user_id", "scheduled_date", name="uq_user_session_date"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    scheduled_date: Mapped[date] = mapped_column(Date, index=True)
    split_label: Mapped[str] = mapped_column(String(64))
    status: Mapped[SessionStatus] = mapped_column(
        SAEnum(SessionStatus, name="session_status"), default=SessionStatus.PLANNED
    )
    source_schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("workout_schedules.id", ondelete="SET NULL")
    )

    user: Mapped[User] = relationship(back_populates="planned_sessions")
    generated_workout: Mapped["GeneratedWorkout | None"] = relationship(
        back_populates="planned_session", uselist=False, cascade="all, delete-orphan"
    )
    completion: Mapped["WorkoutCompletion | None"] = relationship(
        back_populates="planned_session", uselist=False
    )


class GeneratedWorkout(IdTimestampBase):
    __tablename__ = "generated_workouts"

    planned_session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("planned_sessions.id", ondelete="CASCADE"), unique=True
    )
    prescription: Mapped[dict] = mapped_column(JSONB)
    model: Mapped[str] = mapped_column(String(128))
    prompt_version: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    regenerated_count: Mapped[int] = mapped_column(Integer, default=0)

    planned_session: Mapped[PlannedSession] = relationship(back_populates="generated_workout")


class WorkoutCompletion(IdTimestampBase):
    __tablename__ = "workout_completions"

    planned_session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("planned_sessions.id", ondelete="SET NULL")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[CompletionSource] = mapped_column(
        SAEnum(CompletionSource, name="completion_source")
    )
    workout_type: Mapped[str | None] = mapped_column(String(128))
    duration_min: Mapped[float | None] = mapped_column(Numeric(6, 1))
    active_calories: Mapped[float | None] = mapped_column(Numeric(7, 1))
    avg_hr: Mapped[float | None] = mapped_column(Numeric(5, 1))
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    raw_extracted: Mapped[dict | None] = mapped_column(JSONB)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    planned_session: Mapped[PlannedSession | None] = relationship(back_populates="completion")
    pulse_check: Mapped["PulseCheck | None"] = relationship(
        back_populates="completion", uselist=False, cascade="all, delete-orphan"
    )


class PulseCheck(IdTimestampBase):
    __tablename__ = "pulse_checks"

    completion_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("workout_completions.id", ondelete="CASCADE"), unique=True
    )
    rpe: Mapped[int | None] = mapped_column(SmallInteger)
    energy: Mapped[int | None] = mapped_column(SmallInteger)
    soreness: Mapped[int | None] = mapped_column(SmallInteger)
    note: Mapped[str | None] = mapped_column(Text)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)

    completion: Mapped[WorkoutCompletion] = relationship(back_populates="pulse_check")


class BodyMetric(IdTimestampBase):
    __tablename__ = "body_metrics"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    weight_kg: Mapped[float] = mapped_column(Numeric(5, 2))
    body_fat_pct: Mapped[float | None] = mapped_column(Numeric(4, 1))
    lean_mass_kg: Mapped[float | None] = mapped_column(Numeric(5, 2))
    bmi: Mapped[float | None] = mapped_column(Numeric(4, 1))
    extra: Mapped[dict | None] = mapped_column(JSONB)
    source: Mapped[BodyMetricSource] = mapped_column(
        SAEnum(BodyMetricSource, name="body_metric_source")
    )
    raw_extracted: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="body_metrics")


class NutritionLog(IdTimestampBase):
    __tablename__ = "nutrition_logs"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    logged_for_date: Mapped[date] = mapped_column(Date, index=True)
    item_name: Mapped[str] = mapped_column(String(255))
    source: Mapped[NutritionSource] = mapped_column(
        SAEnum(NutritionSource, name="nutrition_source")
    )
    quantity: Mapped[str | None] = mapped_column(String(64))
    calories: Mapped[float | None] = mapped_column(Numeric(7, 1))
    protein_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    carbs_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    fat_g: Mapped[float | None] = mapped_column(Numeric(6, 1))
    off_barcode: Mapped[str | None] = mapped_column(String(64))
    raw_extracted: Mapped[dict | None] = mapped_column(JSONB)

    user: Mapped[User] = relationship(back_populates="nutrition_logs")


class ScheduledJob(IdTimestampBase):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "job_type", "target_date", name="uq_job_user_type_date"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[JobType] = mapped_column(SAEnum(JobType, name="job_type"))
    target_date: Mapped[date | None] = mapped_column(Date)
    run_local_time: Mapped[time | None] = mapped_column(Time)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship(back_populates="scheduled_jobs")


class Event(IdTimestampBase):
    __tablename__ = "events"

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict | None] = mapped_column(JSONB)


__all__ = [
    "Base",
    "User",
    "Profile",
    "Goal",
    "WorkoutSchedule",
    "PlannedSession",
    "GeneratedWorkout",
    "WorkoutCompletion",
    "PulseCheck",
    "BodyMetric",
    "NutritionLog",
    "ScheduledJob",
    "Event",
]
