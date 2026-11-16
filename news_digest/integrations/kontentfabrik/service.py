"""Project operations authorized by KontentFabrik user bindings."""

from __future__ import annotations

from typing import Any

from news_digest.integrations.kontentfabrik.adapter import KontentFabrikAdapter
from news_digest.storage.project_repository import ProjectRepository


class KontentFabrikProjectService:
    """Bridge KontentFabrik's Telegram identity to news_digest-owned projects."""

    def __init__(
        self, adapter: KontentFabrikAdapter, projects: ProjectRepository
    ) -> None:
        self.adapter = adapter
        self.projects = projects

    async def list_projects(self, *, head_user_id: int) -> list[dict[str, Any]]:
        binding = await self.adapter.resolve_binding(head_user_id=head_user_id)
        return await self.projects.list_projects(
            external_user_id=str(binding.worker_user_id)
        )

    async def create_project(
        self, *, head_user_id: int, slug: str, name: str,
        language: str = "ru", timezone: str = "Europe/Moscow",
    ) -> int:
        binding = await self.adapter.resolve_binding(head_user_id=head_user_id)
        return await self.projects.create_project(
            external_user_id=str(binding.worker_user_id), slug=slug, name=name,
            language=language, timezone=timezone,
        )
