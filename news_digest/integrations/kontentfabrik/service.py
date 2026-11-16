"""Project operations authorized by KontentFabrik user bindings."""

from __future__ import annotations

from typing import Any

from news_digest.integrations.kontentfabrik.adapter import (
    KontentFabrikAdapter,
    KontentFabrikBinding,
)
from news_digest.storage.project_repository import ProjectRepository


class KontentFabrikProjectService:
    """Bridge KontentFabrik's Telegram identity to worker-owned projects.

    Every project operation checks ownership against the current worker binding.
    """

    def __init__(
        self, adapter: KontentFabrikAdapter, projects: ProjectRepository
    ) -> None:
        self.adapter = adapter
        self.projects = projects

    async def _owned_binding(
        self, *, head_user_id: int, project_id: int
    ) -> KontentFabrikBinding:
        binding = await self.adapter.resolve_binding(head_user_id=head_user_id)
        owned = await self.projects.list_projects(
            external_user_id=str(binding.worker_user_id)
        )
        if not any(project["id"] == project_id for project in owned):
            raise PermissionError("This project does not belong to your account.")
        return binding

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

    async def set_project_status(
        self, *, head_user_id: int, project_id: int, status: str
    ) -> None:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        await self.projects.set_project_status(project_id=project_id, status=status)

    async def list_sources(
        self, *, head_user_id: int, project_id: int
    ) -> list[dict[str, Any]]:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        return await self.projects.list_sources(project_id=project_id)

    async def add_source(
        self, *, head_user_id: int, project_id: int, url: str,
        name: str | None = None, reliability_score: float = 0.5,
    ) -> int:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        return await self.projects.add_source(
            project_id=project_id, url=url, name=name,
            reliability_score=reliability_score, source_mode="project",
        )

    async def set_source_enabled(
        self, *, head_user_id: int, project_id: int,
        source_id: int, enabled: bool,
    ) -> None:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        await self.projects.set_source_enabled(
            project_id=project_id, source_id=source_id, enabled=enabled
        )

    async def save_rules(
        self, *, head_user_id: int, project_id: int, rules: dict[str, Any]
    ) -> None:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        await self.projects.save_rules(project_id=project_id, rules=rules)

    async def list_targets(
        self, *, head_user_id: int, project_id: int
    ) -> list[dict[str, Any]]:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        return await self.projects.list_targets(project_id=project_id)

    async def add_target(
        self, *, head_user_id: int, project_id: int, target_id: str,
        title: str | None = None, enabled: bool = False,
    ) -> int:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        return await self.projects.add_target(
            project_id=project_id, target_id=target_id, title=title,
            platform="telegram", enabled=enabled,
        )

    async def set_target_enabled(
        self, *, head_user_id: int, project_id: int,
        target_id: str, enabled: bool,
    ) -> None:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        await self.projects.set_target_enabled(
            project_id=project_id, target_id=target_id,
            enabled=enabled, platform="telegram",
        )

    async def set_schedule(
        self, *, head_user_id: int, project_id: int, cron_expression: str,
        timezone: str, enabled: bool,
    ) -> int:
        await self._owned_binding(head_user_id=head_user_id, project_id=project_id)
        return await self.projects.set_schedule(
            project_id=project_id, cron_expression=cron_expression,
            timezone=timezone, enabled=enabled,
        )
