"""Project management for the standalone Telegram bot."""

from __future__ import annotations

from typing import Any

from news_digest.storage.editorial_repository import EditorialRepository
from news_digest.storage.project_repository import ProjectRepository


class StandaloneProjectService:
    """Expose project operations scoped directly to a Telegram user ID."""

    def __init__(self, projects: ProjectRepository, editorial: EditorialRepository) -> None:
        self.projects = projects
        self.editorial = editorial

    async def _owned(self, user_id: int, project_id: int) -> None:
        owned = await self.projects.list_projects(external_user_id=str(user_id))
        if not any(item["id"] == project_id for item in owned):
            raise PermissionError("Проект не найден или не принадлежит вашему аккаунту.")

    async def list_projects(self, *, head_user_id: int) -> list[dict[str, Any]]:
        return await self.projects.list_projects(external_user_id=str(head_user_id))

    async def create_project(
        self, *, head_user_id: int, slug: str, name: str,
        language: str = "ru", timezone: str = "Europe/Moscow",
    ) -> int:
        return await self.projects.create_project(
            external_user_id=str(head_user_id), slug=slug, name=name,
            language=language, timezone=timezone,
        )

    async def update_project_settings(
        self, *, head_user_id: int, project_id: int,
        language: str, timezone: str,
    ) -> None:
        await self._owned(head_user_id, project_id)
        await self.projects.update_project_settings(
            project_id=project_id, language=language, timezone=timezone
        )

    async def set_project_status(
        self, *, head_user_id: int, project_id: int, status: str
    ) -> None:
        await self._owned(head_user_id, project_id)
        await self.projects.set_project_status(project_id=project_id, status=status)

    async def list_sources(self, *, head_user_id: int, project_id: int):
        await self._owned(head_user_id, project_id)
        return await self.projects.list_sources(project_id=project_id)

    async def add_source(
        self, *, head_user_id: int, project_id: int, url: str,
        name: str | None = None, reliability_score: float = 0.5,
        source_mode: str = "project",
    ) -> int:
        await self._owned(head_user_id, project_id)
        return await self.projects.add_source(
            project_id=project_id, url=url, name=name,
            reliability_score=reliability_score, source_mode=source_mode,
        )

    async def set_source_enabled(
        self, *, head_user_id: int, project_id: int, source_id: int, enabled: bool
    ) -> None:
        await self._owned(head_user_id, project_id)
        await self.projects.set_source_enabled(
            project_id=project_id, source_id=source_id, enabled=enabled
        )

    async def save_rules(
        self, *, head_user_id: int, project_id: int, rules: dict[str, Any]
    ) -> None:
        await self._owned(head_user_id, project_id)
        await self.projects.save_rules(project_id=project_id, rules=rules)

    async def list_targets(self, *, head_user_id: int, project_id: int):
        await self._owned(head_user_id, project_id)
        return await self.projects.list_targets(project_id=project_id)

    async def add_target(
        self, *, head_user_id: int, project_id: int, target_id: str,
        title: str | None = None, enabled: bool = False,
    ) -> int:
        await self._owned(head_user_id, project_id)
        return await self.projects.add_target(
            project_id=project_id, target_id=target_id, title=title,
            platform="telegram", enabled=enabled,
        )

    async def set_target_enabled(
        self, *, head_user_id: int, project_id: int, target_id: str, enabled: bool
    ) -> None:
        await self._owned(head_user_id, project_id)
        await self.projects.set_target_enabled(
            project_id=project_id, target_id=target_id,
            enabled=enabled, platform="telegram",
        )

    async def set_schedule(
        self, *, head_user_id: int, project_id: int, cron_expression: str,
        timezone: str, enabled: bool,
    ) -> int:
        await self._owned(head_user_id, project_id)
        return await self.projects.set_schedule(
            project_id=project_id, cron_expression=cron_expression,
            timezone=timezone, enabled=enabled,
        )

    async def get_rules(self, *, head_user_id: int, project_id: int) -> dict[str, Any]:
        await self._owned(head_user_id, project_id)
        return await self.projects.get_rules(project_id=project_id)

    async def get_ai_usage(self, *, head_user_id: int, project_id: int):
        await self._owned(head_user_id, project_id)
        rules = await self.projects.get_rules(project_id=project_id)
        usage = await self.editorial.get_monthly_usage(project_id=project_id)
        return {"usage": usage, "monthly_budget_rub": rules.get("monthly_ai_budget_rub")}
