"""Settings load from the environment, apply defaults, and fail clearly when incomplete."""

import pytest
from pydantic import ValidationError

from lars.config import Settings

REQUIRED_ENV = {
    "TELEGRAM_BOT_TOKEN": "tg-token",
    "ANTHROPIC_API_KEY": "anthropic-key",
    "DATABASE_URL": "postgresql+asyncpg://lars:lars@localhost:5432/lars",
    "ALLOWLIST_TELEGRAM_IDS": "111,222 , 333",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def load() -> Settings:
    """Build Settings from the environment only, ignoring any developer .env file."""
    # Fields come from env; _env_file is a dynamic pydantic-settings kwarg ty can't see.
    return Settings(_env_file=None)  # ty: ignore[missing-argument, unknown-argument]


def test_loads_with_valid_env(env: None) -> None:
    settings = load()

    assert settings.telegram_bot_token == "tg-token"
    assert settings.database_url.endswith("/lars")
    # Comma-separated IDs are parsed (and whitespace tolerated) into ints.
    assert settings.allowlist_telegram_ids == [111, 222, 333]
    assert settings.allowlist == frozenset({111, 222, 333})


def test_applies_defaults(env: None) -> None:
    settings = load()

    assert settings.anthropic_model == "claude-sonnet-4-6"
    assert settings.default_generation_local_time == "20:00"
    assert settings.default_unit_system == "imperial"
    assert settings.log_level == "INFO"


def test_missing_required_raises(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError) as exc:
        load()

    assert "anthropic_api_key" in str(exc.value)
