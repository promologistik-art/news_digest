"""Typed application settings loaded from environment variables."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, StringConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"
    timezone: str = "Europe/Moscow"
    data_dir: Path = Path("./data")

    ai_provider: str = "routerai"
    ai_base_url: str = "https://routerai.ru/api/v1"
    routerai_api_key: SecretStr = SecretStr("")
    ai_model: str = "deepseek/deepseek-v4.1-flash"
    ai_timeout_seconds: float = Field(default=90, gt=0, le=600)
    ai_max_retries: int = Field(default=3, ge=0, le=10)
    ai_input_price_per_million: float = Field(default=11.0, ge=0)
    ai_output_price_per_million: float = Field(default=45.0, ge=0)
    ai_cache_read_price_per_million: float = Field(default=0.23, ge=0)
    ai_cost_currency: str = "RUB"

    telegram_bot_token: SecretStr = SecretStr("")
    telegram_publishing_enabled: bool = False
    kontentfabrik_database_url: SecretStr = SecretStr("")

    database_url: str = "sqlite:///./data/news_digest.sqlite3"
    collection_user_agent: str = "news_digest/0.1"
    collection_timeout_seconds: float = Field(default=25, gt=0, le=300)

    @cached_property
    def database_path(self) -> Path:
        prefix = "sqlite:///"
        if not self.database_url.startswith(prefix):
            raise ValueError("Initial release supports SQLite URLs only.")
        path = Path(self.database_url[len(prefix):])
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
