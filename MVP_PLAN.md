# Lars Bot — MVP Plan

## Problem statement

A small, fixed group of people want a single, low-friction coach that lives where
they already are (Telegram), remembers their training and nutrition, and tells
them what to do next. Existing apps require manual data entry into rigid forms;
this group already produces data as **iPhone screenshots** (Apple Fitness
summaries, a smart-scale app) and would rather talk to a coach than operate an
app. They also forget to log, skip sessions, and need someone to notice and
adjust the plan — not silently let it drift.

## MVP goal

Ship a Telegram bot ("Lars") for an allowlisted set of users that, through
natural conversation and screenshots:

1. Onboards each user into a profile, goals, weekly schedule, timezone, and units.
2. Logs workouts (from Apple Fitness screenshots), weight/body composition (from
   smart-scale screenshots), and nutrition (text / Open Food Facts / label photo).
3. Generates the next workout the night before each scheduled training day.
4. Proactively detects missed workouts and reschedules conversationally.
5. Collects a quick post-workout pulse check that informs future sessions.
6. Keeps each user's data isolated and preserves an audit trail.

**Success in one sentence:** two real users can run a full training week — get
nightly workouts, log via screenshots, miss a session and have Lars notice and
adapt — without ever typing a command.

## User stories

Onboarding & identity
- As a new allowlisted user, when I first message Lars it walks me through a
  short setup (name, age, gender, height, current weight, goal, experience,
  weekly availability, equipment, timezone, units) so it can coach me.
- As a non-allowlisted user, Lars politely declines and stores nothing.

Workouts
- As a user, the night before a training day I receive tomorrow's workout.
- As a user, after training I send an Apple Fitness screenshot and Lars confirms
  the parsed summary and logs it.
- As a user, right after a logged workout I get a <30s pulse check (difficulty,
  energy, soreness, optional note) I can tap through.
- As a user, if I miss a training day Lars reaches out, asks what happened, and
  updates my plan.
- As a user, I can tell Lars "I won't make tomorrow" and it reschedules.

Body metrics
- As a user, I send a smart-scale screenshot and Lars records my weight plus any
  body-fat %, lean mass, or BMI shown, after confirming the numbers.

Nutrition
- As a user, I can say "had a chicken sandwich and a Coke" and Lars records a
  best-effort calorie/macro estimate.
- As a user, I can photograph a nutrition label and Lars reads the calories and
  macros off it.
- As a user, for a branded/barcoded item Lars looks it up in Open Food Facts.

Coaching & memory
- As a user, I can ask "what's today's plan?" or "how's my weight trending?" in
  plain language.
- As a user, Lars never mixes my data with anyone else's.

## Milestones & exit criteria

Each milestone is a thin vertical slice: code + tests + doc updates.

**M0 — Scaffolding & config**
- uv project, Ruff, ty, pytest, Docker Compose Postgres, settings module,
  `.env.example`, CI-style local checks.
- *Exit:* `uv run pytest` green on a trivial test; lint + type-check pass;
  settings load from env with validation.

**M1 — Domain models & persistence foundation**
- Pydantic domain models + SQLAlchemy ORM + Alembic baseline migration for core
  tables (users, profiles, goals, schedules, sessions, logs, jobs, events).
- *Exit:* migrations apply cleanly; repository round-trip integration tests pass
  against Dockerized Postgres.

**M2 — Telegram skeleton + allowlist + echo**
- Async python-telegram-bot app; allowlist gate; handles text, photo, and
  button-tap (callback) updates; structured logging.
- *Exit:* allowlisted user gets a reply; non-allowlisted user is declined and
  nothing is persisted; integration test with a mocked bot.

**M3 — LangGraph workflow + intent routing**
- Single graph: intake → load user context → classify intent → route → persist →
  respond. Postgres checkpointer. Model adapter (Claude Sonnet, text+vision)
  behind a protocol, with a mock for tests. Prompt registry.
- *Exit:* intents route correctly against a mocked adapter; checkpoints persist
  and resume; confirm-before-write enforced for important writes.

**M4 — Onboarding**
- First-message detection → guided onboarding from a markdown prompt → persisted
  profile, goals, schedule, timezone, units.
- *Exit:* a fresh allowlisted user completes onboarding end-to-end (mocked LLM);
  re-messaging does not re-onboard; partial onboarding resumes.

**M5 — Screenshot ingestion (weight + workouts)**
- Photo → vision parse → structured extraction → confirm → persist. Date
  extracted from the image and reconciled to the right date/session.
- *Exit:* given fixture screenshots (mocked vision output), weight and workout
  records are created with the screenshot's date after user confirmation.

**M6 — Scheduling: nightly generation + skip checks**
- JobQueue jobs for nightly generation and skip detection; jobs stored in
  Postgres and rehydrated on startup; per-user timezone; duplicate-job
  prevention; one planned session per scheduled day.
- *Exit:* with an injected clock, the night-before job creates exactly one
  planned session/prescription; restart rehydrates jobs; skip check flags an
  unlogged day.

**M7 — Workout generation workflow**
- LangGraph generation node produces a validated prescription tied to a planned
  session, using history + skips + pulse feedback; no silent regeneration.
- *Exit:* generation returns a schema-valid prescription; a prior skip changes
  the prescription (e.g., repeat/deload) deterministically where rules apply.

**M8 — Pulse check + progression feedback loop**
- Post-completion hybrid survey (conversational + inline buttons) writing RPE,
  energy, soreness, optional note; feedback feeds the next generation.
- *Exit:* completing a workout triggers a skippable pulse check; responses
  persist and are passed into the next generation's context.

**M9 — Nutrition logging**
- NL → Open Food Facts → label photo (vision) → LLM estimate fallback; record
  calories + protein/carbs/fat with source provenance.
- *Exit:* each path produces a nutrition record; branded item resolves via Open
  Food Facts; generic food falls back to estimate; daily totals queryable.

**M10 — Audit trail + operational hardening**
- Events table for important actions; retry/backoff on LLM + Open Food Facts;
  nightly-gen failures surfaced conversationally; graceful degradation.
- *Exit:* important actions emit audit events; injected failures retry then
  surface a clear message; no unhandled exception kills the bot.

## Risks

- **Vision parsing accuracy** — Apple Fitness / scale layouts vary; misreads.
  *Mitigation:* always confirm parsed values; store raw extraction for review.
- **JobQueue is in-memory** — jobs lost on restart. *Mitigation:* persist jobs in
  Postgres and rehydrate on startup (M6).
- **Open Food Facts coverage** — weak for generic/home food. *Mitigation:*
  best-effort tiered fallback to label photo and LLM estimate; mark provenance.
- **LLM nondeterminism** — generation/intent variance. *Mitigation:* keep
  identity/scheduling deterministic; validate outputs to schema; mock in tests.
- **LLM/API failure during unattended nightly jobs.** *Mitigation:* retry with
  backoff; surface failure to the user conversationally.
- **Prompt injection via free text/screenshots.** Low risk (trusted allowlist)
  but business writes go through confirmation and never execute arbitrary actions.
- **Cost** — vision calls per screenshot. Low volume (few users) but monitored.

## Non-goals (MVP)

See `README.md` → Non-goals. Summary: no open registration, no parsed set/rep/
load history, no guaranteed-accurate nutrition, no multi-agent/Temporal/vector
memory, no web UI/charts, no horizontal scaling.

## Resolved decisions (pre-M0)

These were the original open questions; all are now decided.

1. **Session lifecycle** — states `planned → generated → completed | skipped |
   missed`. `generated` set by the night-before job; `completed` by a confirmed
   log; `skipped` when the user acknowledges a miss; `missed` when the skip-check
   finds an unlogged day past grace with no acknowledgement. `skipped`/`missed`
   are terminal unless the user reschedules (which moves/creates a planned
   session). → `planned_sessions.status` enum in M1.
2. **Schedule representation** — **fixed weekly** (weekday → split map). No rolling
   cycle in the MVP. → `workout_schedules.definition`.
3. **Skip behavior** — **ask each time**: Lars offers "push to next day (shift the
   cycle)" vs "just skip it this week"; the user decides per incident. No
   automatic global shift/drop. → handled in M6/M7 + conversational-flows.
4. **Skip-check timing & grace** — proactive check on the **training day evening
   (default 21:00 local), ~3h grace**; pings only if nothing logged. → `skip_check`
   job in M6. Configurable via `workout_schedules.skip_check_grace_hours`.
5. **Goal/schedule refresh** — **periodic (~every 4 weeks) + on trigger** (weight
   stalls vs goal, or adherence drops noticeably). → `goal_review` job + simple
   trend thresholds; refine thresholds in M8/M10.
6. **Multiple/unplanned workouts** — allowed: a logged workout attaches to that
   day's planned session if date+split match, else stored as an unplanned extra
   (`planned_session_id = null`).
7. **Data correction** — conversational: user states the correction, Lars
   re-confirms and updates the record, retaining original `raw_extracted` + an
   audit event. No special command.

## Open questions (to resolve as we build)

- Exact trend thresholds for the goal-refresh trigger (weight-stall window,
  adherence-drop %). *Refine in M8/M10 with real data.*
