"""Configuration tests."""

from news_digest.config import Settings


def test_routerai_environment_variable(monkeypatch) -> None:
    monkeypatch.setenv("ROUTERAI_API_KEY", "local-test-key")
    settings = Settings(_env_file=None)
    assert settings.routerai_api_key.get_secret_value() == "local-test-key"


def test_publishing_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.telegram_publishing_enabled is False
