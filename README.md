# Lars Bot

A personal-coach Telegram bot for a small, fixed group of users that tracks
workouts, body weight, and nutrition, and generates each user's next workout the
night before a scheduled training day.

> **Status: building — M2 (Telegram skeleton & allowlist) complete.** The repo holds
> the design artifacts (`MVP_PLAN.md`, `TASKS.md`, `docs/`) plus a working
> persistence layer and a runnable Telegram bot skeleton: allowlist gate and
> handlers for text/photo/button updates (placeholder replies; real intent
> handling lands with the LangGraph workflow in M3).

## What Lars does

Lars talks like a person — **there are no slash commands.** Everything happens
through natural-language chat plus a few quick tap-buttons. Most data arrives as
**iPhone screenshots** that Lars reads with vision:

- **Workouts** — you send an Apple Fitness workout-summary screenshot; Lars
  extracts type/duration/calories/HR, confirms it, and logs the session.
- **Weight & body composition** — you send a smart-scale app screenshot; Lars
  records weight plus any body-fat %, lean mass, or BMI shown.
- **Nutrition** — you describe a meal, send a barcode/branded item (looked up in
  Open Food Facts), or photograph a nutrition label; Lars records calories and
  protein/carbs/fat (best effort).

Lars also:

- Runs guided **onboarding** the first time an allowlisted user messages it.
- Generates **tomorrow's workout the night before** a scheduled training day.
- **Proactively notices missed workouts** and reaches out to reschedule.
- Sends a **<30-second post-workout pulse check** (difficulty / energy /
  soreness, plus an optional note) that informs the next session.
- **Confirms before writing** anything important (weight, schedule changes,
  marking a workout done/skipped) and just acknowledges trivial logs.

## MVP scope

In scope for the MVP:

- Allowlisted multi-user support (each Telegram ID = one user), with isolated data.
- Guided onboarding → user profile + goals + weekly schedule + timezone + units.
- Screenshot-based workout logging (Apple Fitness summaries).
- Screenshot-based body-metrics logging (smart-scale app).
- Nutrition logging via natural language, Open Food Facts, and label photos.
- Nightly workout generation tied to a planned session (prescription model).
- Proactive missed-workout detection and conversational rescheduling.
- Post-workout pulse check.
- Audit trail of important events.

## Non-goals (MVP)

- Public/open registration — Lars only talks to allowlisted IDs.
- Parsing per-exercise sets/reps/load from screenshots (Apple Fitness summaries
  don't contain it). Progression is prescription + adherence + self-reported
  feedback, **not** a measured load history.
- A full nutrition database or guaranteed-accurate calorie counts (best effort).
- Multi-agent orchestration, Temporal, or vector memory for business facts.
- Web/mobile UI, charts/graphs, social features, payments.
- Horizontal scaling — a single bot instance is assumed.

## Architecture summary

Layered, single-process:

```
Telegram (text / photo / button taps)
        │
  Telegram interface layer  ── python-telegram-bot (async) + JobQueue
        │
  Application/service layer ── onboarding, logging, nutrition, schedule, workout
        │
  LangGraph workflow layer  ── intake → load context → classify intent → route → persist → respond
        │
  Domain models  ·  Model adapter (Claude Sonnet, text+vision)  ·  Nutrition adapter (Open Food Facts)
        │
  Persistence (Postgres = source of truth)  ·  LangGraph Postgres checkpointer
```

Postgres is the system of record for all business facts. LangGraph's Postgres
checkpointer holds workflow/conversation state. Scheduled jobs (nightly
generation, skip checks) live in Postgres and are **rehydrated into the
in-memory JobQueue on startup**. See [`docs/architecture.md`](docs/architecture.md).

## Tech stack (intended)

- Python 3.11+, managed with **uv**; linted with **Ruff**; type-checked with **ty**.
- **python-telegram-bot** (async) + **JobQueue** for chat and scheduling.
- **LangGraph** for the stateful workflow + checkpointing.
- **Claude Sonnet** via the Anthropic API, behind a thin adapter (model name
  configurable). Vision used for screenshot/label parsing.
- **Open Food Facts** API for branded/barcode nutrition lookups.
- **Postgres** + **Alembic** migrations.
- **pytest** for tests; Docker Compose for local Postgres.

## Local setup

```bash
# 1. Install deps (works today)
uv sync

# 2. Start Postgres (works today — host port 5433)
docker compose up -d db

# 3. Configure environment (works today)
cp .env.example .env   # then fill in the values below

# 4. Run migrations (works today)
uv run alembic upgrade head

# 5. Run the bot (works today — needs a real TELEGRAM_BOT_TOKEN in .env)
uv run lars
```

Checks (works today): `uv run ruff check .`, `uv run ty check`, `uv run pytest`.
Integration tests need the Postgres container running; they skip otherwise.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | Bot token from @BotFather. |
| `ANTHROPIC_API_KEY` | yes | Anthropic API key. |
| `ANTHROPIC_MODEL` | no | Sonnet model id (default e.g. `claude-sonnet-4-6`). Configurable. |
| `DATABASE_URL` | yes | Postgres connection string. |
| `ALLOWLIST_TELEGRAM_IDS` | yes | Comma-separated Telegram user IDs allowed to use Lars. |
| `DEFAULT_GENERATION_LOCAL_TIME` | no | Default night-before generation time, local (default `20:00`). |
| `DEFAULT_TIMEZONE` | no | Fallback timezone until onboarding captures one (default `America/New_York`). |
| `DEFAULT_UNIT_SYSTEM` | no | `imperial` (default) or `metric`. |
| `LOG_LEVEL` | no | Default `INFO`. |

## Development workflow

- Build in **thin vertical slices**: code + tests + doc updates per slice.
- Every commit updates `CHANGELOG.md` (Keep a Changelog format) and keeps this
  README matching what actually works.
- `uv run ruff check .` and `uv run ty` must pass; `uv run pytest` green.
- LLM and time-dependent behavior is tested against a mocked adapter and an
  injected clock — never against the live API.

## Documents

- [`MVP_PLAN.md`](MVP_PLAN.md) — problem, goal, user stories, milestones, risks, open questions.
- [`TASKS.md`](TASKS.md) — sequential, test-backed checklist by milestone.
- [`docs/architecture.md`](docs/architecture.md) — modules, flows, scheduling, memory, failure handling.
- [`docs/data-model.md`](docs/data-model.md) — entities, relationships, tables.
- [`docs/conversational-flows.md`](docs/conversational-flows.md) — intents and example dialogs.
- [`docs/workout-generation.md`](docs/workout-generation.md) — how workouts are generated; rules vs model.
