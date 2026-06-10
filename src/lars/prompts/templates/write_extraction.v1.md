The user wants to record something. Turn their message into a single JSON object.

Intent: {intent}
Today's date: {today}
Current training schedule (weekday -> split): {current_schedule}

Set "kind" from the intent:
- log_weight -> "weight"
- log_workout -> "workout"
- change_schedule -> "schedule"
- report_skip -> "skip"

Fill ONLY the fields relevant to the kind:
- weight: weight_kg (convert pounds to kilograms), body_fat_pct (or null).
- workout: workout_type, duration_min (or null), performed_on (ISO date; default today).
- schedule: schedule = the FULL new weekday->split map AFTER applying the request to
  the current schedule, using lowercase 3-letter weekdays (mon, tue, ...).
- skip: skip_date (ISO date; resolve "today"/"tomorrow"/weekday names from today's date).

Always set "summary": a short confirmation of what will be recorded, e.g.
"Log bodyweight 82.4 kg", "Move legs to Saturday", "Mark Mon 2026-06-09 as skipped".

Output ONLY the JSON object. No markdown fences, no commentary.

User message:
{message}
