from __future__ import annotations

import pytest

from news_digest.storage.database import Database
from news_digest.storage.editorial_repository import EditorialRepository
from news_digest.storage.project_repository import ProjectRepository
from news_digest.telegram_commands import dispatch
from news_digest.telegram_service import StandaloneProjectService


@pytest.mark.asyncio
async def test_standalone_news_commands_create_and_list_own_projects(tmp_path) -> None:
    database_path = tmp_path / "standalone.sqlite3"
    await Database(database_path).initialize()
    service = StandaloneProjectService(
        ProjectRepository(database_path), EditorialRepository(database_path)
    )

    created = await dispatch(service, 12345, "create", "culture | Culture")
    assert "создан" in created
    project_id = int(created.split("ID ")[1].split(")")[0])

    listed = await dispatch(service, 12345, "projects", "")
    assert f"#{project_id} Culture" in listed
    assert "draft" in listed


@pytest.mark.asyncio
async def test_standalone_service_rejects_access_to_another_users_project(tmp_path) -> None:
    database_path = tmp_path / "standalone-isolation.sqlite3"
    await Database(database_path).initialize()
    repository = ProjectRepository(database_path)
    project_id = await repository.create_project(
        external_user_id="111", slug="private", name="Private project"
    )
    service = StandaloneProjectService(
        repository, EditorialRepository(database_path)
    )

    with pytest.raises(PermissionError):
        await service.set_project_status(
            head_user_id=222, project_id=project_id, status="active"
        )


@pytest.mark.asyncio
async def test_standalone_news_commands_configure_sources_and_schedule(tmp_path) -> None:
    database_path = tmp_path / "standalone-settings.sqlite3"
    await Database(database_path).initialize()
    service = StandaloneProjectService(
        ProjectRepository(database_path), EditorialRepository(database_path)
    )
    created = await dispatch(service, 12345, "create", "updates | Updates")
    project_id = int(created.split("ID ")[1].split(")")[0])

    source = await dispatch(
        service, 12345, "addsource",
        f"{project_id} | https://example.org/rss.xml | Example | project",
    )
    schedule = await dispatch(
        service, 12345, "schedule",
        f"{project_id} | 0 8 * * * | Europe/Moscow | on",
    )

    assert "Источник добавлен" in source
    assert "Расписание" in schedule
