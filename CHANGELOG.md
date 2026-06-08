# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added (M14 — dynamic activity level)
- `ActivityService` derives an effective activity level from completed workouts in
  the last week (bumped by reported untracked activity) and refreshes
  `profile.activity_level` during the weekly review, so TDEE adapts to reality.
- Daily next-morning follow-up (`activity_check` job type) asking about untracked
  activity (walk, yardwork, on-your-feet) via inline buttons; the tap is recorded
  as an `untracked_activity` event and feeds the derivation. Created at onboarding.
- Callback routing: `actq:` buttons are handled directly (outside the graph).
- Tests: derivation mapping, refresh-from-workouts, and the untracked-activity bump.

### Changed (M13 — adaptive review: weekly check-in + block level-set)
- The recurring check-in is now one mechanism with two depths: a light **weekly**
  review most weeks (inputs logged, wins, misses that matter), and a deep **block**
  review every ~4-6 weeks (weight/goal/program level-set + at most one adjustment).
- Lars schedules the next block date adaptively (`users.next_block_review_on`,
  migration) — sooner when the user is struggling, later when steady.
- Reviews always send but stay brief, via a scope-aware `review` prompt; the
  scheduled job calls `SummaryService.scheduled_review` (on-demand `view_trends`
  still uses the period-based summary).
- Tests: first review is a block review that schedules the next; weekly reviews
  don't move the block date.

### Added (M12 — weekly/monthly summaries)
- `SummaryService` compiles a period's stats (workouts completed/skipped/missed,
  weight latest + change, average daily calories, current metrics) and has the
  model phrase a short check-in (`summary` prompt).
- Scheduled **weekly summary** job (Sunday evening, per-user local time) added as a
  `weekly_summary` job type (enum migration), created at onboarding and rehydrated
  into the JobQueue like the other jobs.
- "Answer if asked" path: the `view_trends` intent routes to a summary node
  (weekly by default, monthly when the message mentions a month).
- Tests: stat aggregation over the window, adapter rendering, unknown-user, and
  the view-trends routing (weekly vs monthly).

### Note
- A scheduled *monthly* summary is deferred (JobQueue has no native monthly
  trigger); monthly summaries are available on demand ("how's my month?").

### Added (M11 — health metrics foundation)
- `healthsciencecalculator` dependency and a `HealthMetricsService` computing BMI,
  BMR (Harris-Benedict), TDEE, and a goal-based daily calorie target from the
  user's profile and most recent weight.
- `ActivityLevel` enum + `profiles.activity_level` column (migration); onboarding
  now asks activity level and current weight, storing the weight as an initial
  body-metric reading.
- Workout generation now includes the user's metrics (BMI/TDEE/calorie target)
  in its context.
- Tests: metrics computation and the no-weight None case; onboarding persists
  activity level and the initial weight.

### Added (CI)
- GitHub Actions workflow (`.github/workflows/ci.yml`) running ruff, ty, and pytest
  on push/PR, with a Postgres service so the integration tests run (not skip).

### Added (M10 — audit trail & operational hardening)
- `retry_async` helper (exponential backoff, injectable sleep) and a
  `RetryingModelAdapter` wrapping the Claude adapter; Open Food Facts lookups also
  retry transient HTTP errors.
- Nightly generation failures are caught, surfaced to the user conversationally,
  and recorded as a `nightly_gen_failed` audit event.
- A global Telegram error handler logs the exception and notifies the user, so a
  single failed update can't crash the bot.
- Tests: retry-then-succeed / exhaustion, the retrying adapter, nightly-failure
  surfacing + audit event, the error handler, and an explicit audit-event check.

### Added (M9 — nutrition logging)
- Open Food Facts adapter (`OpenFoodFactsClient.by_barcode` → calories + macros,
  per serving with a 100g fallback).
- `NutritionService.log_from_text`: a pure-digit message is treated as a barcode
  and resolved via Open Food Facts; otherwise the model estimates items + macros
  (`nutrition_extraction` prompt). Each record stores its source/provenance and
  quantity. The reply includes the running daily totals.
- `log_nutrition` graph node for the nutrition intent (replaces the placeholder
  trivial-write path).
- Nutrition-label photos: the screenshot extractor now classifies
  `nutrition_label` and the screenshot persister logs it (source `label_photo`).
- `NutritionRepository` with `add` and `daily_totals`.
- Tests: Open Food Facts parsing (mock transport), text-estimate and barcode
  logging paths with provenance, and daily-totals accumulation.

### Added (M8 — pulse check & progression feedback)
- Post-workout pulse check: after a confirmed workout screenshot, the graph runs a
  hybrid survey (conversational message + inline tap-buttons) for difficulty/RPE,
  energy, and soreness, plus an optional free-text note. Fully skippable.
- Inline-keyboard support end-to-end: `TurnReply` carries button options, handlers
  render an `InlineKeyboardMarkup`, and `handle_callback` resumes the graph on a tap.
- `pulse_check` persists a `PulseCheck` linked to the workout completion
  (`DbPulsePersister`); body-metric screenshots do not trigger a survey.
- The pulse feeds the next workout generation (a hard recent RPE → hold).
- Tests: workout → survey → persist (with value mapping), skippable, body-metrics
  no-survey, and an integration test that a hard last pulse yields a hold directive.

### Changed
- The screenshot persister now returns the workout completion id so the pulse
  check can link to it; `run_turn` returns a `TurnReply` (str + options).

### Added (M7 — workout generation)
- `WorkoutGenerator`: builds context (split, history, deload-after-skip, recent
  pulse), prompts the model (`workout_generation` prompt), validates a
  `WorkoutPrescription`, and persists a `GeneratedWorkout` tied to the planned
  session (status → generated).
- Deterministic guardrails: split resolved from the schedule, a prior
  skipped/missed comparable session forces a deload directive, a hard recent RPE
  forces a hold, and there is no silent regeneration — an existing prescription is
  reused unless regeneration is explicitly requested (`regenerated_count` bumped).
- The nightly job now generates the prescription and sends it to the user
  (`format_prescription`).
- Tests: valid prescription persisted + session marked generated, progress with no
  history, deload after a missed session, and the no-silent-regeneration guardrail.

### Added (M6 — scheduling: nightly generation & skip checks)
- `Clock` abstraction (`SystemClock`) so time-dependent logic is testable.
- `SchedulingService`: `generate_for_tomorrow` ensures exactly one planned session
  for the user's next training day (idempotent, per-user timezone), and
  `run_skip_check` marks unlogged training days past their grace period as missed.
- `ScheduledJobRepository` (durable job store) with idempotent `ensure`; onboarding
  now creates the user's `nightly_generation` and `skip_check` rows.
- JobQueue wiring (`scheduler/jobs.py`): per-user `run_daily` jobs registered by
  name (dedup on re-register), rehydrated from Postgres at startup, and lazily
  registered for a user after their first message; the skip-check job messages the
  user about unlogged sessions.
- Tests: nightly creates exactly one session (idempotent) and skips rest days,
  skip-check flags/respects grace, job-store `ensure` idempotency, and
  registration dedup.

### Added (M5 — screenshot ingestion)
- Vision ingestion for Apple Fitness workout summaries and smart-scale readings:
  photo → `ScreenshotExtractor` (Claude vision) → `ScreenshotExtraction`
  (kind, confidence, summary, screenshot date, canonical fields).
- A clarity gate: low-confidence/unclear screenshots ask for a clearer photo
  instead of guessing.
- Screenshot path in the graph: confirm the parsed summary, then persist a
  `body_metrics` or `workout_completion` record (with raw extraction stored),
  using the date read from the screenshot. Workouts reconcile to a planned
  session on that date and mark it completed.
- Photo handler downloads the image and runs extract → confirm → persist;
  `DbScreenshotPersister` and a `ScreenshotExtractor` are wired in at startup.
- Tests: extraction parsing, the clarity gate, confirm/reject/persist flow
  (in-memory), and Postgres integration (body-metric date; workout reconciliation).

### Changed
- `intake` now reads each turn's input from an `incoming` payload (text or
  screenshot), so the graph handles photos as well as text without state bleed.

### Added (M4 — onboarding & live workflow)
- Guided multi-turn onboarding: a new user (no DB row) is routed into an
  onboarding node that asks profile/goal/schedule/timezone/unit questions via
  LangGraph `interrupt`, then a model call extracts a validated `OnboardingResult`
  (`onboarding_extraction` prompt) and persists user + profile + goal + schedule.
- `DbContextLoader` (first-message detection) and `DbOnboardingPersister`
  (`services/onboarding.py`), plus an `onboarding_completed` audit event.
- `run_turn` conversation runner that starts or resumes a graph turn and returns
  the pending question/confirmation or final response.
- The graph is now wired into the live Telegram text handler, with the Postgres
  checkpointer and graph built at startup (`post_init`) and torn down on shutdown.
- Tests: in-memory onboarding (collect → persist once, partial resume) and a
  Postgres integration test (persists the user aggregate; re-messaging routes
  normally instead of re-onboarding).

### Changed
- `intake` resets transient state each fresh turn so values can't bleed across
  turns on a reused thread; `confirmed` is now tri-state (None / True / False).

### Added (M3 — LangGraph workflow & model adapter)
- Model adapter Protocol (`generate`, `generate_with_images`) with an Anthropic
  (Claude, text + vision) implementation and a scripted `MockModelAdapter`.
- Prompt registry loading versioned markdown templates by key
  (`src/lars/prompts/`), with an intent-classification prompt.
- `Intent` enum and a LangGraph workflow:
  intake → load_context → classify → route → (confirm_write) → persist → respond.
- Confirm-before-write gate via LangGraph `interrupt`: important-write intents
  pause until the user confirms; trivial writes persist directly; new users
  short-circuit to onboarding.
- Postgres checkpointer helper (`AsyncPostgresSaver`) for durable graph state.
- Tests: intent routing and confirm/reject flow (in-memory), and a Postgres
  integration test proving checkpoint state persists/resumes across instances.

### Note
- The graph is not yet wired into the live Telegram handlers — M2's placeholder
  replies remain until M4 (onboarding) gives the graph real behavior. The
  `persist` node is a placeholder; real writes land in later milestones.

### Added (M2 — Telegram skeleton & allowlist)
- Async python-telegram-bot application bootstrap (`src/lars/telegram/app.py`)
  with handlers for text, photo, and callback-query (button) updates.
- Allowlist gate keyed on Telegram user id: allowlisted users get a placeholder
  acknowledgement, others are politely declined (`src/lars/telegram/handlers.py`).
- `uv run lars` console entry point (`src/lars/cli.py`) and structured logging
  setup (`src/lars/logging_config.py`).
- Handler tests covering allowlisted/declined paths for text, photo, and
  callbacks, plus application wiring.

### Added (M1 — domain models & persistence)
- Shared domain enums (`src/lars/domain/enums.py`) and a Pydantic
  `WorkoutPrescription` value object for the generated-workout JSON payload.
- Async SQLAlchemy 2.0 ORM models for all 12 core tables
  (`src/lars/persistence/models.py`) plus engine/session factory (`db.py`).
- Alembic (sync via psycopg) with an autogenerated baseline migration creating
  the full schema; URL sourced from `DATABASE_URL`.
- Repository layer with explicit Protocols: `UserRepository`, `BodyMetricRepository`.
- Integration tests (skip if Postgres unavailable) that apply migrations to a
  throwaway database and round-trip the user and body-metric aggregates.

### Changed
- Standardized on the psycopg3 driver (`postgresql+psycopg://`) for both the
  async app engine and sync migrations.
- Local Postgres now published on host port **5433** (avoids clashing with a
  Postgres already on 5432).

### Added (M0 — scaffolding & config)
- uv project (`pyproject.toml`, Python 3.11+) with Ruff, ty, and pytest configured.
- `docker-compose.yml` with a Postgres 16 service for local dev.
- `.env.example` documenting all environment variables.
- `src/lars/config/settings.py`: typed Pydantic settings loaded/validated from the
  environment, with comma-separated allowlist parsing and a cached `get_settings()`.
- Tests covering settings loading, defaults, and clear failure on missing required vars.

### Removed
- `PLAN.md` — original brief, fully superseded by README/MVP_PLAN/TASKS/docs.

### Added
- Phase-1 design artifacts: rewritten `README.md`, `MVP_PLAN.md`, `TASKS.md`, and
  `docs/` (architecture, data-model, conversational-flows, workout-generation).
- Resolved all pre-M0 open questions: session lifecycle, fixed-weekly schedule,
  ask-each-time skip behavior, skip-check timing (~21:00 local, 3h grace),
  periodic+trigger goal refresh, unplanned-workout handling, conversational data
  correction. Added `goal_review` job type and skip-check schedule fields.
