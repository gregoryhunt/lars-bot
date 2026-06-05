"""Prompt registry loads and renders versioned templates."""

from lars.prompts import PromptRegistry


def test_render_intent_classification() -> None:
    registry = PromptRegistry()
    out = registry.render(
        "intent_classification",
        intents="- log_weight\n- view_plan",
        message="I weighed 180 this morning",
    )
    assert "I weighed 180 this morning" in out
    assert "log_weight" in out
    # No unsubstituted placeholders remain.
    assert "{message}" not in out
    assert "{intents}" not in out
