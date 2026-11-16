from __future__ import annotations

import pytest

from news_digest.config import Settings
from news_digest.storage.database import Database
from news_digest.telegram_admin import TelegramAdminService


def test_telegram_admin_ids_parse_comma_separated_values() -> None:
    settings = Settings(telegram_admin_ids="12345, 67890")
    assert settings.telegram_admin_id_set == frozenset({12345, 67890})


def test_invalid_telegram_admin_id_is_rejected() -> None:
    settings = Settings(telegram_admin_ids="12345,not-a-number")
    with pytest.raises(ValueError, match="TELEGRAM_ADMIN_IDS"):
        _ = settings.telegram_admin_id_set


@pytest.mark.asyncio
async def test_telegram_admin_service_scopes_projects_to_telegram_user(tmp_path) -> None:
    database_path = tmp_path / "telegram-admin.sqlite3"
    await Database(database_path).initialize()
    service = TelegramAdminService(str(database_path))
    project_id = await service.create_project(
        head_user_id=12345, slug="private-news", name="Private news"
    )

    projects = await service.list_projects(head_user_id=12345)
    assert [project["id"] for project in projects] == [project_id]
    assert await service.list_projects(head_user_id=67890) == []

    with pytest.raises(PermissionError, match="не принадлежит"):
        await service.set_project_status(
            head_user_id=67890, project_id=project_id, status="active"
        )
