"""Typed application settings, loaded and validated from the environment."""

from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """All configuration Lars needs, sourced from env vars (and an optional .env)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Required
    telegram_bot_token: str
    anthropic_api_key: str
    database_url: str
    # Comma-separated in the environment; parsed into a list below.
    allowlist_telegram_ids: Annotated[list[int], NoDecode]

    # Optional (defaults)
    anthropic_model: str = "claude-sonnet-4-6"
    default_generation_local_time: str = "20:00"
    default_timezone: str = "America/New_York"
    default_unit_system: str = "imperial"
    log_level: str = "INFO"

    @field_validator("allowlist_telegram_ids", mode="before")
    @classmethod
    def _split_ids(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(part) for part in value.split(",") if part.strip()]
        return value

    @property
    def allowlist(self) -> frozenset[int]:
        """The set of Telegram user IDs permitted to use Lars."""
        return frozenset(self.allowlist_telegram_ids)


@lru_cache
def get_settings() -> Settings:
    """Return cached settings, loaded once per process."""
    return Settings()  # ty: ignore[missing-argument]  # values come from env/.env
