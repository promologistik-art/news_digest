from __future__ import annotations

import pytest

from news_digest.integrations.kontentfabrik.adapter import (
    KontentFabrikAdapter,
    KontentFabrikBinding,
)
from news_digest.integrations.kontentfabrik.service import KontentFabrikProjectService
from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository


class FakeAdapter:
    async def resolve_binding(self, *, head_user_id: int) -> KontentFabrikBinding:
        assert head_user_id == 12345
        return KontentFabrikBinding(
            head_user_id=12345, worker_user_id=67890, bot_type="news_digest",
            clone_id=1, bot_username="news_digest_bot", db_prefix="nd_",
        )


@pytest.mark.asyncio
async def test_kontentfabrik_identity_scopes_projects_to_worker_user(tmp_path) -> None:
    path = tmp_path / "kf.sqlite3"
    await Database(path).initialize()
    service = KontentFabrikProjectService(
        FakeAdapter(), ProjectRepository(path)
    )
    project_id = await service.create_project(
        head_user_id=12345, slug="culture", name="Culture"
    )
    result = await service.list_projects(head_user_id=12345)
    assert len(result) == 1
    assert result[0]["id"] == project_id


def test_adapter_requires_database_url() -> None:
    with pytest.raises(ValueError, match="KONTENTFABRIK_DATABASE_URL"):
        KontentFabrikAdapter("")
