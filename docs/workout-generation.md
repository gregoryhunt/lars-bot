# Workout generation

Lars generates a workout **the night before** each scheduled training day. The
content is produced by an LLM node, but the *decisions about when, whether, and
for which session* to generate are deterministic and live in code. This split is
deliberate: the model is good at prescribing exercises; it must not be the source
of truth for scheduling or session identity.

## The "prescription + completion" model

Apple Fitness workout summaries (our primary completion input) contain
type/duration/calories/HR — **not** per-exercise sets, reps, or load. So Lars
does **not** maintain a measured load history. Instead:

- Lars stores the **prescription** it gave (exercises, sets, reps, target loads/
  durations, notes).
- The screenshot confirms the session **happened** and supplies high-level
  metrics.
- The **pulse check** (RPE, energy, soreness, optional note) supplies the
  subjective signal.

Progression is therefore driven by **the last prescription + adherence + pulse
feedback + any text the user volunteers**, not by reading back actual weights.

## Inputs to a generation

For a given planned session, the generation node assembles:

- **User profile & goal** — experience, equipment access, goal type (cut/bulk/etc.).
- **Schedule context** — the split label for the day (e.g. Pull), and where it
  sits in the weekly cycle.
- **Last comparable session(s)** — the previous prescription for this split and
  its status (completed/skipped/missed).
- **Recent pulse feedback** — RPE/energy/soreness trends and notes
  (e.g. "left elbow cranky").
- **Adherence/skips** — recent skip/miss pattern.
- **Latest body metrics & nutrition trend** — light context (e.g. weight
  trending down on a cut), not a hard input.

## Deterministic vs model-driven

**Deterministic (code — never the LLM):**
- *When* to generate: the night-before job at the user's local generation time.
- *Which* session: resolved from the active schedule → exactly one
  `planned_session` per `(user_id, scheduled_date)`.
- *Whether* to generate: only if the session has no prescription yet
  (no silent regeneration — see below).
- The **split label** for the day comes from the schedule, not the model.
- **Deload-after-skip guardrail:** if the immediately prior comparable session
  was `skipped`/`missed`, the next prescription repeats or lightly deloads that
  session rather than progressing it. (Exact rule finalized in M7.)
- **Output validation:** the model's output is validated against the prescription
  schema; invalid output is retried, then falls back to a safe template.
- **Units:** target loads render in the user's unit system; equipment-specific kg
  overrides are respected.

**Model-driven (LLM, within those rails):**
- Exercise selection appropriate to the split, equipment, and experience.
- Set/rep/intensity prescription and sensible progression from the last
  prescription.
- Adjustments for pulse feedback (e.g. reduce pulling volume given an elbow note).
- Coaching notes / framing in Lars's voice.

## How skips affect generation

| Prior comparable session | Effect on next prescription |
|---|---|
| `completed`, pulse "easy/just right" | progress modestly (small load/volume bump) |
| `completed`, pulse "hard/brutal" or high soreness | hold or trim volume |
| `skipped` / `missed` (one) | repeat or lightly deload; don't progress |
| repeated skips | simplify/shorten; Lars may ask if the schedule needs changing |

Skips are detected proactively (the `skip_check` job runs the training-day
evening, ~21:00 local, with ~3h grace) or volunteered by the user. When a skip is
handled, Lars **asks each time** whether to push the session to the next day
(shifting the fixed-weekly cycle) or just drop it for the week — there is no
automatic global shift. Either way the `planned_session.status` is updated before
the next generation reads it.

## No silent regeneration

Once a session has a prescription, Lars does **not** regenerate it automatically.
A user can explicitly ask for changes ("make tomorrow's lighter"), which
regenerates, bumps `regenerated_count`, and writes an audit event. This prevents
the plan from churning underneath the user.

## Failure handling

- The nightly generation call uses retry with backoff.
- If it still fails, Lars **surfaces it conversationally** ("I hit a snag building
  tomorrow's workout — I'll retry and send it shortly") and emits a
  `nightly_gen_failed` event, rather than failing silently or leaving the session
  without a plan.
- A safe deterministic template is the last-resort fallback so the user is never
  left with nothing on a training day.

## Determinism for tests

Generation is tested with the **mock LLM adapter**: given fixed context, the node
must return schema-valid output, and the deterministic guardrails (split
resolution, single-session dedup, deload-after-skip, no-silent-regeneration) must
hold independently of model output.
