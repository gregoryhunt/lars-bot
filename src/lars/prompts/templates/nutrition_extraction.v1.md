Estimate, item by item, the calories and macros for the meal the user described.
Best effort is fine.

Return a single JSON object with this shape:
- items: an array of objects, each with: name (string), quantity (string or null,
  e.g. "1 cup", "2 servings"), calories (number or null), protein_g (number or
  null), carbs_g (number or null), fat_g (number or null).

Rules:
- Estimate reasonable values for typical portions; if the user cooked something and
  listed ingredients, estimate from the raw ingredients.
- Output ONLY the JSON object. No markdown fences, no commentary.

User message:
{message}

JSON:
