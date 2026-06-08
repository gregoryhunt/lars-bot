# Lars Bot — Tasks

Sequential, test-backed checklist grouped by milestone (see `MVP_PLAN.md`).
Keep tasks small; each should land as a vertical slice with tests + doc updates.

## M0 — Scaffolding & config
- [x] Initialize uv project + `pyproject.toml` (Python 3.11+), package `lars`.
- [x] Add Ruff + ty config; add `pytest` with one trivial passing test.
- [x] Add `docker-compose.yml` with a Postgres service.
- [x] Add `.env.example` with all env vars from the README.
- [x] `config/settings.py`: typed settings (Pydantic) loaded + validated from env.
- [x] Test: settings load with valid env; fail clearly on missing required vars.

## M1 — Domain models & persistence foundation
- [x] Pydantic domain models + enums (see `docs/data-model.md`).
- [x] SQLAlchemy ORM models for core tables.
- [x] Alembic init + baseline migration creating all core tables.
- [x] Repository layer (per aggregate) with explicit interfaces.
- [x] Integration test: migrations apply; repo create/read round-trips on Postgres.

## M2 — Telegram skeleton + allowlist
- [x] Async python-telegram-bot app bootstrap + entrypoint (`uv run lars`).
- [x] Allowlist middleware/gate keyed on Telegram user id.
- [x] Handlers registered for text, photo, and callback-query (button) updates.
- [x] Structured logging setup.
- [x] Test: allowlisted user gets a reply; non-allowlisted declined, nothing persisted.

## M3 — LangGraph workflow + model adapter
- [x] Model adapter protocol (`generate`, `generate_with_images`) + Anthropic impl.
- [x] Mock adapter for tests.
- [x] Prompt registry module (markdown prompts loaded by key + version).
- [x] LangGraph graph: intake → load context → classify intent → route → persist → respond.
- [x] Postgres checkpointer wired in.
- [x] Confirm-before-write gate for important writes.
- [x] Test: intents route correctly (mock adapter); checkpoint persists/resumes;
      important write blocked until confirmation.
- [x] Wire the graph into the live Telegram handlers (done in M4).

## M4 — Onboarding
- [x] First-message detection (no user row → onboarding).
- [x] Onboarding prompt (markdown) + multi-turn flow capturing profile/goals/
      schedule/timezone/units.
- [x] Persist profile, goals, schedule, timezone, units.
- [x] Test: fresh user completes onboarding (mock LLM); re-message doesn't re-onboard;
      partial onboarding resumes from checkpoint.

## M5 — Screenshot ingestion (weight + workouts)
- [x] Photo download + pass to vision adapter.
- [x] Vision extraction → structured fields for (a) Apple Fitness workout,
      (b) smart-scale body metrics.
- [x] Date extracted from image; reconcile to the correct date/planned session.
- [x] Confirm parsed values via message before persisting.
- [x] Persist workout_completion / body_metrics with raw extraction stored.
- [x] Test: fixture screenshots (mock vision) → records created with screenshot
      date after confirmation; low-confidence parse asks rather than guesses.

## M6 — Scheduling: nightly generation + skip checks
- [x] Job store table + repository; rehydrate JobQueue from Postgres on startup.
- [x] Per-user nightly generation job at user-local time; duplicate prevention.
- [x] One planned session per scheduled training day (unique constraint).
- [x] Skip-check job: flag an unlogged training day past grace period.
- [x] Injected clock abstraction for tests.
- [x] Test: night-before job creates exactly one session/prescription; restart
      rehydrates jobs; skip check flags unlogged day; no duplicate jobs.
      (Prescription generation itself is M7; M6 creates the planned session.)

## M7 — Workout generation workflow
- [x] Generation node: build context (schedule, history, skips, pulse feedback) →
      LLM prescription → validate to schema → persist tied to planned session.
- [x] Deterministic guardrails (split resolution, dedup, deload-after-skip rule).
- [x] No silent regeneration (regenerate only on explicit user request).
- [x] Test: schema-valid prescription returned; prior skip changes prescription
      per rule; regeneration requires explicit request.
      (Wired into the nightly job, which now generates + sends the workout.)

## M8 — Pulse check + progression feedback
- [x] Post-completion hybrid survey (message + inline buttons): RPE, energy, soreness.
- [x] Optional free-text note; whole survey skippable; no nagging.
- [x] Persist pulse_check linked to completion; feed into next generation context.
- [x] Test: completion triggers skippable pulse check; responses persist; next
      generation receives pulse context.

## M9 — Nutrition logging
- [x] Open Food Facts adapter (barcode → calories + macros per serving).
- [x] Nutrition-label photo parse (vision) → calories + macros.
- [x] LLM estimate fallback for generic/home-cooked (raw-ingredient judgment).
- [x] Quantity handling + provenance (source) on each record.
- [x] Daily totals query.
- [x] Test: each path creates a record; branded resolves via OFF; generic falls
      back to estimate; daily totals correct.

## M10 — Audit trail + hardening
- [x] Events/audit table + emit on important actions.
- [x] Retry/backoff wrapper for LLM + OFF calls.
- [x] Nightly-gen failure surfaced to user conversationally.
- [x] Global error handling so no handler crash kills the bot.
- [x] Test: audit events emitted; injected failures retry then surface message;
      handler exception is caught and reported.
