from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from news_digest.integrations.kontentfabrik.adapter import KontentFabrikBinding
from news_digest.integrations.kontentfabrik.service import KontentFabrikProjectService
from news_digest.integrations.kontentfabrik.telegram import _dispatch
from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository


class FakeAdapter:
    async def resolve_binding(self, *, head_user_id: int) -> KontentFabrikBinding:
        worker_id = 67890 if head_user_id == 12345 else 99999
        return KontentFabrikBinding(
            head_user_id=head_user_id, worker_user_id=worker_id,
            bot_type="news_digest", clone_id=1,
            bot_username="news_digest_bot", db_prefix="nd_",
        )


@pytest.mark.asyncio
async def test_kontentfabrik_commands_create_and_configure_owned_project(tmp_path) -> None:
    path = tmp_path / "management_commands.sqlite3"
    await Database(path).initialize()
    service = KontentFabrikProjectService(
        FakeAdapter(), ProjectRepository(path)
    )

    created = await _dispatch(service, 12345, "create", "culture | Culture")
    assert "создан" in created
    project_id = int(created.split("ID ")[1].split(")")[0])

    await _dispatch(
        service, 12345, "addsource",
        f"{project_id} | https://example.org/feed.xml | Example",
    )
    await _dispatch(
        service, 12345, "rules",
        f'{project_id} | {json.dumps({"topics": ["кино"], "max_age_hours": 48})}',
    )
    await _dispatch(
        service, 12345, "addtarget",
        f"{project_id} | @culture_news | Culture channel",
    )
    await _dispatch(
        service, 12345, "schedule",
        f"{project_id} | 0 8 * * * | Europe/Moscow | off",
    )
    result = await _dispatch(service, 12345, "projects", "")
    assert "Culture" in result
    assert "draft" in result


@pytest.mark.asyncio
async def test_kontentfabrik_commands_reject_cross_user_project_access(tmp_path) -> None:
    path = tmp_path / "management_isolation.sqlite3"
    await Database(path).initialize()
    repository = ProjectRepository(path)
    project_id = await repository.create_project(
        external_user_id="67890", slug="private", name="Private project"
    )
    service = KontentFabrikProjectService(FakeAdapter(), repository)

    with pytest.raises(PermissionError):
        await service.set_project_status(
            head_user_id=22222, project_id=project_id, status="active"
        )


@pytest.mark.asyncio
async def test_status_and_boolean_commands_are_validated(tmp_path) -> None:
    path = tmp_path / "management_validation.sqlite3"
    await Database(path).initialize()
    service = KontentFabrikProjectService(FakeAdapter(), ProjectRepository(path))
    await _dispatch(service, 12345, "create", "test | Test")
    with pytest.raises(ValueError, match="Unsupported"):
        await _dispatch(service, 12345, "status", "1 | running")
    with pytest.raises(ValueError, match="on or off"):
        await _dispatch(service, 12345, "target-toggle", "1 | @test | maybe")
