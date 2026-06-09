"""Local prompt playground — exercise Lars's prompts against the real model.

Only needs an Anthropic key (no database, no Telegram). Set ANTHROPIC_API_KEY in
your shell or a local .env, then:

    uv run python scripts/playground.py classify "I weighed 181 this morning"
    uv run python scripts/playground.py generate --split pull --progression deload
    uv run python scripts/playground.py nutrition "chicken caesar wrap and a banana"
    uv run python scripts/playground.py onboarding
    uv run python scripts/playground.py review --scope block
    uv run python scripts/playground.py screenshot path/to/screenshot.png

Add --show-prompt to print the rendered prompt too (handy when tweaking a template
in src/lars/prompts/templates/ — edit the .md and re-run).
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel

from lars.adapters.llm import Image
from lars.adapters.llm.anthropic import AnthropicAdapter
from lars.domain.enums import Intent
from lars.domain.models import (
    NutritionEstimate,
    OnboardingResult,
    ScreenshotExtraction,
    WorkoutPrescription,
)
from lars.prompts import PromptRegistry
from lars.workflow.onboarding import format_answers

_SAMPLE_ONBOARDING = {
    "name": "Greg",
    "age_and_sex": "34, male",
    "height": "5'11\"",
    "weight": "182 lb",
    "activity": "moderately active",
    "goal": "lose fat, target around 175",
    "experience": "intermediate",
    "schedule": "push monday, pull wednesday, legs friday",
    "equipment": "full gym",
    "timezone": "US Eastern",
    "units": "imperial",
}


def _adapter() -> AnthropicAdapter:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY is not set (export it or put it in a local .env).")
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    return AnthropicAdapter(api_key, model)


def _strip_fences(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    return text


def _show(prompt: str, output: str, *, show_prompt: bool) -> None:
    if show_prompt:
        print("--- rendered prompt ---\n" + prompt + "\n--- end prompt ---\n")
    print("--- model output ---\n" + output + "\n")


def _validate(output: str, model: type[BaseModel]) -> None:
    try:
        parsed = model.model_validate(json.loads(_strip_fences(output)))
    except Exception as exc:  # noqa: BLE001 - playground: surface any parse/validation issue
        print(f"✗ does NOT parse into {model.__name__}: {exc}")
        return
    print(f"✓ valid {model.__name__}:\n{parsed.model_dump_json(indent=2)}")


async def cmd_classify(args: argparse.Namespace, registry: PromptRegistry) -> None:
    prompt = registry.render(
        "intent_classification",
        intents="\n".join(f"- {i.value}" for i in Intent),
        message=args.message,
    )
    output = await _adapter().generate(prompt)
    _show(prompt, output, show_prompt=args.show_prompt)
    print(f"→ parsed intent: {Intent.parse(output).value}")


async def cmd_generate(args: argparse.Namespace, registry: PromptRegistry) -> None:
    prompt = registry.render(
        "workout_generation",
        split=args.split,
        progression=args.progression,
        experience=args.experience,
        equipment=args.equipment,
        goal=args.goal,
        metrics=args.metrics,
        last_workout=args.last_workout,
        feedback=args.feedback,
    )
    output = await _adapter().generate(prompt, system=registry.persona())
    _show(prompt, output, show_prompt=args.show_prompt)
    _validate(output, WorkoutPrescription)


async def cmd_nutrition(args: argparse.Namespace, registry: PromptRegistry) -> None:
    prompt = registry.render("nutrition_extraction", message=args.message)
    output = await _adapter().generate(prompt)
    _show(prompt, output, show_prompt=args.show_prompt)
    _validate(output, NutritionEstimate)


async def cmd_onboarding(args: argparse.Namespace, registry: PromptRegistry) -> None:
    prompt = registry.render("onboarding_extraction", answers=format_answers(_SAMPLE_ONBOARDING))
    output = await _adapter().generate(prompt)
    _show(prompt, output, show_prompt=args.show_prompt)
    _validate(output, OnboardingResult)


async def cmd_review(args: argparse.Namespace, registry: PromptRegistry) -> None:
    values: dict[str, Any] = {
        "scope": args.scope,
        "window_days": 7 if args.scope == "weekly" else 28,
        "completed": 3,
        "skipped": 1,
        "missed": 0,
        "weight_latest": "82.0 kg",
        "weight_change": "-0.6 kg",
        "avg_calories": "2100.0 cal",
        "metrics": "BMI 24.7 (healthy), TDEE ~2800 cal, calorie target ~2300 cal",
    }
    prompt = registry.render_map("review", values)
    output = await _adapter().generate(prompt, system=registry.persona())
    _show(prompt, output, show_prompt=args.show_prompt)


async def cmd_persona(args: argparse.Namespace, registry: PromptRegistry) -> None:
    print(registry.persona())


async def cmd_screenshot(args: argparse.Namespace, registry: PromptRegistry) -> None:
    path = Path(args.path)
    if not path.is_file():
        sys.exit(f"No such file: {path}")
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    prompt = registry.get("screenshot_extraction")
    output = await _adapter().generate_with_images(prompt, [Image(path.read_bytes(), media)])
    _show(prompt, output, show_prompt=args.show_prompt)
    _validate(output, ScreenshotExtraction)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Exercise Lars's prompts locally.")
    parser.add_argument("--show-prompt", action="store_true", help="print the rendered prompt")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("classify", help="classify a message into an intent")
    p.add_argument("message")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("generate", help="generate a workout prescription")
    p.add_argument("--split", default="pull")
    p.add_argument("--progression", default="progress", choices=["progress", "hold", "deload"])
    p.add_argument("--experience", default="intermediate")
    p.add_argument("--equipment", default="full gym")
    p.add_argument("--goal", default="cut")
    p.add_argument("--metrics", default="TDEE ~2800 cal, calorie target ~2300 cal")
    p.add_argument("--last-workout", dest="last_workout", default="none")
    p.add_argument("--feedback", default="none")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("nutrition", help="estimate calories/macros for a meal description")
    p.add_argument("message")
    p.set_defaults(func=cmd_nutrition)

    p = sub.add_parser("onboarding", help="extract a profile from sample onboarding answers")
    p.set_defaults(func=cmd_onboarding)

    p = sub.add_parser("review", help="render a weekly/block review from sample stats")
    p.add_argument("--scope", default="weekly", choices=["weekly", "block"])
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("screenshot", help="parse a workout/scale/label screenshot")
    p.add_argument("path")
    p.set_defaults(func=cmd_screenshot)

    p = sub.add_parser("persona", help="print the shared persona/system prompt")
    p.set_defaults(func=cmd_persona)

    return parser


def main() -> None:
    load_dotenv()
    args = _build_parser().parse_args()
    asyncio.run(args.func(args, PromptRegistry()))


if __name__ == "__main__":
    main()
