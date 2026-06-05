"""Onboarding helpers: persister interface and model-output parsing."""

import json
from typing import Protocol

from lars.domain.models import OnboardingResult


class OnboardingPersister(Protocol):
    """Persists a completed onboarding result for a user."""

    async def __call__(self, telegram_id: int, result: OnboardingResult) -> None: ...


def format_answers(answers: dict[str, str]) -> str:
    """Render the collected question/answer pairs for the extraction prompt."""
    return "\n".join(f"- {key}: {value}" for key, value in answers.items())


def parse_onboarding_json(raw: str) -> OnboardingResult:
    """Parse the model's JSON (tolerating code fences) into an OnboardingResult."""
    text = raw.strip()
    if text.startswith("```"):
        # Drop the opening fence (``` or ```json) and the closing fence.
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return OnboardingResult.model_validate(json.loads(text))
