from __future__ import annotations

import pytest

from news_digest.config import Settings


def test_admin_telegram_ids_are_parsed_from_environment(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "12345, 67890")
    settings = Settings(_env_file=None)
    assert settings.admin_telegram_ids_set == frozenset({12345, 67890})


def test_invalid_admin_telegram_id_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TELEGRAM_IDS", "not-a-number")
    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="ADMIN_TELEGRAM_IDS"):
        _ = settings.admin_telegram_ids_set
