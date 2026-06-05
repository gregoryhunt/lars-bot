# Changelog

All notable changes to this project are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

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
