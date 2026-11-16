from __future__ import annotations

import asyncpg
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



@pytest.mark.asyncio
async def test_adapter_uses_read_only_registry_connection_and_maps_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    class FakeConnection:
        async def fetchrow(self, query, *args):
            captured["query"] = query
            captured["args"] = args
            return {
                "head_user_id": 12345,
                "worker_user_id": 67890,
                "bot_type": "news_digest",
                "clone_id": 3,
                "bot_username": "news_digest_bot",
                "db_prefix": "nd_3_",
            }

        async def close(self):
            captured["closed"] = True

    async def fake_connect(database_url, *, server_settings):
        captured["database_url"] = database_url
        captured["server_settings"] = server_settings
        return FakeConnection()

    monkeypatch.setattr(asyncpg, "connect", fake_connect)
    adapter = KontentFabrikAdapter(
        "postgresql+asyncpg://readonly:secret@example.com/kontentfabrik"
    )

    binding = await adapter.resolve_binding(head_user_id=12345)

    assert binding == KontentFabrikBinding(
        head_user_id=12345,
        worker_user_id=67890,
        bot_type="news_digest",
        clone_id=3,
        bot_username="news_digest_bot",
        db_prefix="nd_3_",
    )
    assert captured["database_url"].startswith("postgresql://")
    assert captured["server_settings"] == {"default_transaction_read_only": "on"}
    assert captured["args"] == (12345, "news_digest")
    assert "user_bindings" in captured["query"]
    assert captured["closed"] is True
