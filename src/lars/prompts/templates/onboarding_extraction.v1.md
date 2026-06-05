You are setting up a new user for Lars, a fitness and nutrition coaching bot.
Below are the user's answers to onboarding questions. Convert them into a single
JSON object that exactly matches the required schema.

Required JSON keys:
- display_name: string — what to call the user.
- age: integer or null.
- sex: string or null — as the user described it.
- height_cm: number or null — convert any height (e.g. feet/inches) to centimeters.
- experience_level: one of beginner, intermediate, advanced, or null.
- equipment_access: array of short strings (e.g. "full gym", "dumbbells", "home").
- goal_type: one of cut, bulk, maintain, recomp. Map "lose fat" to cut and
  "build muscle" to bulk.
- target_weight_kg: number or null — convert pounds to kilograms if given.
- timezone: an IANA timezone string. Map plain descriptions, e.g. "US Eastern"
  to America/New_York, "US Pacific" to America/Los_Angeles, "UK" to Europe/London.
- unit_system: imperial or metric. Default to imperial if the user says lb/miles.
- schedule: an object mapping lowercase 3-letter weekdays to a split label,
  e.g. mon to push, wed to pull, fri to legs.
- generation_local_time: 24-hour HH:MM; use 20:00 unless the user specified one.

Rules:
- Output ONLY the JSON object. No markdown fences, no commentary.
- If a value is unknown, use null (or an empty array/object as appropriate).

User's answers:
{answers}

JSON:
