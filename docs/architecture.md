# Architecture

Lars is a **single-process, async Python application**. python-telegram-bot owns
the event loop and the in-process JobQueue; LangGraph runs the per-message
workflow; Postgres is the source of truth. There is no separate web server and no
horizontal scaling in the MVP.

## Module boundaries

```
src/lars/
  config/        settings.py            typed settings from env
  domain/        models.py, enums.py    Pydantic domain models, state enums
  persistence/   db.py, models.py,       SQLAlchemy engine/session, ORM,
                 repositories/           repository interfaces + impls
  telegram/      app.py, handlers.py,    bot bootstrap, update handlers,
                 keyboards.py            inline-keyboard builders
  workflow/      graph.py, state.py,     LangGraph graph, graph state,
                 nodes/                  node implementations
  services/      onboarding.py,          application services orchestrating
                 logging_service.py,     domain + persistence (no Telegram or
                 nutrition.py,           LLM specifics leak in)
                 schedule.py, workout.py
  adapters/      llm/ (base, anthropic,  model provider behind a Protocol;
                 mock), nutrition/       Open Food Facts client
                 (openfoodfacts.py)
  scheduler/     jobs.py, rehydrate.py   job definitions + startup rehydration
  prompts/       registry.py, *.md       prompt registry + markdown prompts
```

Dependency direction is strictly inward: `telegram` → `workflow`/`services` →
`domain`/`persistence`/`adapters`. The workflow and service layers never import
`telegram`; the domain never imports infrastructure. Adapters are referenced
through Protocols so they can be mocked in tests.

### Responsibilities

- **telegram** — translate Telegram updates (text, photo, button taps) into a
  normalized input, invoke the workflow, render responses and keyboards. No
  business logic.
- **workflow (LangGraph)** — the single graph that drives each turn: load
  context, classify intent, route, call services, produce a reply. Holds
  conversational state via the Postgres checkpointer.
- **services** — deterministic business operations (persist a weight log,
  resolve today's plan, apply a schedule change). Reusable from both the graph
  and scheduled jobs.
- **adapters** — `llm` (Claude Sonnet, text + vision) and `nutrition`
  (Open Food Facts). Thin, swappable, mockable.
- **persistence** — Postgres via SQLAlchemy; repositories expose intent-named
  methods, not raw queries, to callers.
- **scheduler** — defines JobQueue jobs and rehydrates them from Postgres on
  startup.

## The workflow graph

One graph, kept deliberately simple:

```
intake ──▶ load_user_context ──▶ classify_intent ──▶ route
                                                       │
        ┌──────────────┬─────────────┬────────────────┼───────────────┐
        ▼              ▼             ▼                 ▼               ▼
   onboarding   log_workout    log_weight        log_nutrition   coaching/Q&A
   (multi-turn) (vision)       (vision)          (NL/OFF/vision)  (read-only)
        │              │             │                 │               │
        └──────────────┴─────────────┴────────┬────────┴───────────────┘
                                               ▼
                                  confirm_if_important ──▶ persist ──▶ respond
```

- **classify_intent** uses the LLM (with the command-free intent taxonomy in
  `conversational-flows.md`). New users short-circuit to **onboarding**.
- **confirm_if_important** gates writes: schedule changes, weight, marking a
  workout done/skipped, and any vision-parsed values must be echoed and confirmed
  before `persist`. Trivial acknowledgements skip the gate.
- Workout generation is **not** in this per-message graph by default — it runs
  from the scheduled job (see below) and reuses the same generation node/service.
  A user can also explicitly request generation, which routes here.

## Event flows

**Inbound message (text):** Telegram update → handler normalizes → graph
(`intake`→…→`respond`) → reply. State checkpointed per user thread.

**Inbound screenshot:** photo handler downloads the image → graph routes to the
vision-backed log node → adapter returns structured extraction (incl. the
date on the screenshot) → `confirm_if_important` echoes parsed values → on
confirmation, service persists with the screenshot's date.

**Button tap (pulse check / confirmations):** callback-query handler maps the
callback data to the awaiting workflow step → graph resumes from checkpoint →
persists.

**Nightly generation (background):** JobQueue fires at the user's local
generation time the night before a training day → generation service builds
context (schedule, history, skips, recent pulse feedback) → LLM prescription →
validated → persisted as the planned session's workout → Lars sends it.

**Skip detection (background):** a scheduled check finds training days that are
past their grace period with no completion → marks the session and sends a
conversational nudge; the user's reply updates the schedule. Users may also
volunteer a miss first.

## Scheduling approach

- python-telegram-bot **JobQueue** runs all timed work in-process.
- **JobQueue is in-memory** and does not survive restarts. Therefore every
  durable job is persisted in a `scheduled_jobs` table, and on startup
  `scheduler/rehydrate.py` reads that table and re-registers the jobs. The table
  is the source of truth; JobQueue is a runtime cache.
- Each user has a **timezone**; generation and skip-check times are computed in
  user-local time.
- **Duplicate prevention:** jobs are keyed by `(user_id, job_type, target_date)`;
  re-registration is idempotent. A planned session has a unique
  `(user_id, scheduled_date)` constraint so generation can't double-create.
- **Failures** are retried with backoff; a persistent nightly-generation failure
  is surfaced to the user as a message rather than dying silently.

## Memory strategy

- **Postgres = canonical business facts** (profiles, goals, schedules, sessions,
  logs, jobs, events). Nothing critical lives only in the LLM.
- **LangGraph Postgres checkpointer = workflow/conversational state** — the
  current turn's progress, in-flight multi-step flows (onboarding, pulse check),
  and recent conversational context per user thread.
- **Generated summaries / coaching context** (optional) may be derived and cached
  but are always rebuildable from Postgres; they are never authoritative.
- **No vector memory** for business facts.

## State ownership

| State | Owner |
|---|---|
| Users, profiles, goals, schedules | Postgres (services) |
| Planned/completed/skipped sessions, prescriptions | Postgres |
| Body metrics, nutrition logs, pulse checks | Postgres |
| Scheduled jobs (durable) | Postgres → rehydrated into JobQueue |
| In-flight conversation / multi-step flow state | LangGraph checkpointer (Postgres) |
| Audit/event log | Postgres |

## Failure handling

- **LLM / Open Food Facts calls:** wrapped with retry + backoff; on exhaustion,
  degrade gracefully (e.g., fall back to LLM estimate for nutrition; for nightly
  generation, message the user that the plan is delayed).
- **Vision misreads:** mitigated by mandatory confirmation and by storing the raw
  extraction alongside the structured record for later correction.
- **Bot-level:** a global error handler ensures a single failed update never
  crashes the process; the error is logged and, where user-facing, acknowledged.
- **Idempotency:** scheduled writes (planned sessions, jobs) are idempotent by
  key so retries and restarts don't duplicate data.

## Testing strategy

- **Unit:** domain logic, generation guardrails, intent routing — against the
  **mock LLM adapter**.
- **Integration:** repositories, migrations, and scheduler rehydration against a
  **Dockerized Postgres**; an **injected clock** drives time-dependent jobs.
- The live Anthropic and Open Food Facts APIs are never called in tests.
