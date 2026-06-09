Generate the workout for the user's upcoming session.

Session split: {split}
Progression directive: {progression}
  - progress: add a little load or volume vs the last session.
  - hold: keep load/volume similar (the last session felt hard, or the user was sore).
  - deload: reduce volume/intensity (the user recently skipped or missed a session).
User experience: {experience}
Available equipment: {equipment}
Goal: {goal}
Health metrics: {metrics}
Last session's workout (for reference): {last_workout}
Recent feedback: {feedback}

Produce a single JSON object with these keys:
- split_label: the session split (string).
- exercises: an array of objects, each with: name (string), sets (integer or null),
  reps (string or null, e.g. "8-10"), target_load (string or null, e.g. "135 lb" or
  "bodyweight"), target_duration_min (number or null), notes (string or null).
- session_notes: a short coaching note (string or null).

Rules:
- Choose exercises appropriate to the split, equipment, and experience.
- Honor the progression directive.
- Output ONLY the JSON object. No markdown fences, no commentary.
