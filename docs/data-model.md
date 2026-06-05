# Data model

Postgres is the system of record. This document describes the core entities,
their relationships, and suggested tables. Column lists are a starting point for
the M1 baseline migration, not a frozen schema — the session lifecycle and a few
columns are expected to evolve (see Open questions in `MVP_PLAN.md`).

Conventions: every table has `id` (UUID), `created_at`, `updated_at` unless
noted. Money/measurement values store a canonical unit plus the user's display
preference is applied at render time. Raw vision extractions are stored as
`jsonb` next to the structured record for auditing and correction.

## Entities & relationships

```
user 1───1 profile
user 1───* goal            (one active at a time; history retained)
user 1───* workout_schedule (effective-dated; one active)
user 1───* planned_session
user 1───* body_metric
user 1───* nutrition_log
user 1───* scheduled_job
user 1───* event

planned_session 1───0..1 generated_workout
planned_session 1───0..1 workout_completion
workout_completion 1───0..1 pulse_check
```

## Tables

### users
Identity and per-user settings.
- `telegram_id` (bigint, unique, not null) — the only login identity.
- `display_name`
- `timezone` (IANA, e.g. `America/New_York`)
- `unit_system` (`imperial` | `metric`)
- `status` (`onboarding` | `active` | `paused`)

Allowlisting is enforced in the app from config, not a DB table, for the MVP.

### profiles
One per user; the basic picture captured at onboarding.
- `user_id` (fk, unique)
- `age` (int)
- `sex` (enum/text)
- `height` (canonical cm)
- `experience_level` (`beginner` | `intermediate` | `advanced`)
- `equipment_access` (jsonb — e.g. tags like `barbell`, `dumbbells`, `gym`, `home`)
- `notes` (text — freeform context from onboarding)

### goals
Versioned; one `is_active = true` per user.
- `user_id` (fk)
- `type` (`cut` | `bulk` | `maintain` | `recomp`)
- `target_weight` (canonical kg, nullable)
- `target_date` (date, nullable)
- `rationale` (text)
- `is_active` (bool)

History is kept by inserting a new row and deactivating the prior one (audited).

### workout_schedules
Effective-dated weekly plan; one active schedule per user. **Fixed-weekly model**
(weekday → split); no rolling cycle in the MVP.
- `user_id` (fk)
- `definition` (jsonb) — weekday → split label
  (`{"mon":"push","wed":"pull","fri":"legs"}`).
- `generation_local_time` (time, default from settings, e.g. `20:00`)
- `skip_check_local_time` (time, default `21:00`)
- `skip_check_grace_hours` (int, default 3 — grace before pinging)
- `effective_from` (date), `effective_to` (date, nullable)
- `is_active` (bool)

### planned_sessions
One per scheduled training day. The spine of the workout lifecycle.
- `user_id` (fk)
- `scheduled_date` (date) — **unique with `user_id`** to prevent duplicates.
- `split_label` (text — e.g. `push`)
- `status` (`planned` | `generated` | `completed` | `skipped` | `missed`)
- `source_schedule_id` (fk → workout_schedules)

State transitions (see `workout-generation.md`): `planned` → `generated`
(night-before job) → `completed` (logged) | `skipped` (user-acknowledged) |
`missed` (auto-detected, unlogged past grace).

### generated_workouts
The prescription produced for a planned session.
- `planned_session_id` (fk, unique)
- `prescription` (jsonb) — schema-validated structure: ordered exercises with
  sets/reps/target load or duration, plus coaching notes.
- `model` (text — model id used), `prompt_version` (text)
- `generated_at`
- `regenerated_count` (int, default 0) — bumped only on explicit user request.

### workout_completions
What actually happened, primarily parsed from an Apple Fitness screenshot.
- `planned_session_id` (fk, nullable — unplanned sessions allowed later)
- `user_id` (fk)
- `source` (`apple_fitness_screenshot` | `manual` | `other`)
- `workout_type` (text — e.g. `Traditional Strength Training`)
- `duration_min` (numeric)
- `active_calories` (numeric, nullable)
- `avg_hr` (numeric, nullable)
- `performed_at` (timestamptz) — **taken from the screenshot**, not receipt time.
- `raw_extracted` (jsonb)
- `confirmed_at` (timestamptz)

Note: Apple Fitness summaries do not contain per-exercise set/rep/load, so those
are intentionally absent. Progression relies on the prescription + pulse feedback.

### pulse_checks
Quick post-workout survey; at most one per completion.
- `completion_id` (fk, unique)
- `rpe` (smallint — overall difficulty, e.g. 1–10)
- `energy` (smallint)
- `soreness` (smallint)
- `note` (text, nullable — optional free text)
- `skipped` (bool — true if the user dismissed it)

### body_metrics
Weight and body-composition, primarily from a smart-scale screenshot.
- `user_id` (fk)
- `measured_at` (timestamptz) — **from the screenshot**.
- `weight` (canonical kg, not null)
- `body_fat_pct` (numeric, nullable)
- `lean_mass` (canonical kg, nullable)
- `bmi` (numeric, nullable)
- `extra` (jsonb, nullable — any additional fields the scale showed)
- `source` (`smart_scale_screenshot` | `manual`)
- `raw_extracted` (jsonb)

### nutrition_logs
One row per logged item; daily totals are derived by querying a date.
- `user_id` (fk)
- `logged_for_date` (date)
- `item_name` (text)
- `source` (`open_food_facts` | `label_photo` | `llm_estimate` | `manual`)
- `quantity` (text/numeric — best effort; e.g. "1 serving", grams)
- `calories` (numeric)
- `protein_g`, `carbs_g`, `fat_g` (numeric)
- `off_barcode` (text, nullable — when resolved via Open Food Facts)
- `raw_extracted` (jsonb, nullable — label OCR / OFF payload / estimate basis)

### scheduled_jobs
Durable record of timed work; rehydrated into JobQueue on startup.
- `user_id` (fk)
- `job_type` (`nightly_generation` | `skip_check` | `goal_review`)
- `target_date` (date, nullable) — for one-off date-bound jobs.
- `run_local_time` (time) / `next_run_at` (timestamptz)
- `is_active` (bool)
- `last_run_at`, `last_status` (text)
- Unique on `(user_id, job_type, target_date)` for idempotent re-registration.

### events (audit trail)
Append-only log of important actions.
- `user_id` (fk, nullable)
- `event_type` (text — e.g. `workout_generated`, `session_skipped`,
  `goal_changed`, `weight_logged`, `nightly_gen_failed`)
- `payload` (jsonb)
- `created_at`

## What lives where: Postgres vs derived context

**Postgres (canonical):** users, profiles, goals, schedules, planned/generated/
completed/skipped sessions, body metrics, nutrition logs, pulse checks, scheduled
jobs, events.

**LangGraph checkpointer (Postgres-backed, workflow state):** in-flight
conversation, multi-step flow progress (onboarding, pulse check), recent
conversational context per user thread. Managed by LangGraph's own tables — not
hand-modeled here.

**Derived / optional (rebuildable, never authoritative):** generated coaching
summaries, trend rollups (e.g. weekly weight average), adherence stats. Computed
from canonical tables on demand or cached; safe to drop and recompute.

**Never stored in LLM memory or vectors:** any of the canonical facts above.
