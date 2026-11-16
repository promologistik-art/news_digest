"""Standalone Telegram administration for the news_digest worker."""

from __future__ import annotations

import logging
from typing import Any

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from news_digest.config import Settings
from news_digest.integrations.kontentfabrik.telegram import HELP, _dispatch
from news_digest.storage.editorial_repository import EditorialRepository
from news_digest.storage.project_repository import ProjectRepository

logger = logging.getLogger(__name__)


class TelegramAdminService:
    """Project service scoped to the Telegram administrator's own projects."""

    def __init__(self, database_path: str) -> None:
        self.projects = ProjectRepository(database_path)
        self.editorial = EditorialRepository(database_path)

    async def _assert_owner(self, user_id: int, project_id: int) -> None:
        projects = await self.projects.list_projects(external_user_id=str(user_id))
        if not any(project["id"] == project_id for project in projects):
            raise PermissionError("Этот проект не принадлежит вашему Telegram-аккаунту.")

    async def list_projects(self, *, head_user_id: int) -> list[dict[str, Any]]:
        return await self.projects.list_projects(external_user_id=str(head_user_id))

    async def create_project(self, *, head_user_id: int, slug: str, name: str) -> int:
        return await self.projects.create_project(
            external_user_id=str(head_user_id), slug=slug, name=name
        )

    async def update_project_settings(
        self, *, head_user_id: int, project_id: int, language: str, timezone: str
    ) -> None:
        await self._assert_owner(head_user_id, project_id)
        await self.projects.update_project_settings(
            project_id=project_id, language=language, timezone=timezone
        )

    async def set_project_status(
        self, *, head_user_id: int, project_id: int, status: str
    ) -> None:
        await self._assert_owner(head_user_id, project_id)
        await self.projects.set_project_status(project_id=project_id, status=status)

    async def list_sources(
        self, *, head_user_id: int, project_id: int
    ) -> list[dict[str, Any]]:
        await self._assert_owner(head_user_id, project_id)
        return await self.projects.list_sources(project_id=project_id)

    async def add_source(
        self, *, head_user_id: int, project_id: int, url: str,
        name: str | None = None, source_mode: str = "project",
    ) -> int:
        await self._assert_owner(head_user_id, project_id)
        return await self.projects.add_source(
            project_id=project_id, url=url, name=name, source_mode=source_mode
        )

    async def set_source_enabled(
        self, *, head_user_id: int, project_id: int, source_id: int, enabled: bool
    ) -> None:
        await self._assert_owner(head_user_id, project_id)
        await self.projects.set_source_enabled(
            project_id=project_id, source_id=source_id, enabled=enabled
        )

    async def save_rules(
        self, *, head_user_id: int, project_id: int, rules: dict[str, Any]
    ) -> None:
        await self._assert_owner(head_user_id, project_id)
        await self.projects.save_rules(project_id=project_id, rules=rules)

    async def list_targets(
        self, *, head_user_id: int, project_id: int
    ) -> list[dict[str, Any]]:
        await self._assert_owner(head_user_id, project_id)
        return await self.projects.list_targets(project_id=project_id)

    async def add_target(
        self, *, head_user_id: int, project_id: int,
        target_id: str, title: str | None = None, enabled: bool = False,
    ) -> int:
        await self._assert_owner(head_user_id, project_id)
        return await self.projects.add_target(
            project_id=project_id, target_id=target_id, title=title,
            platform="telegram", enabled=enabled,
        )

    async def set_target_enabled(
        self, *, head_user_id: int, project_id: int,
        target_id: str, enabled: bool,
    ) -> None:
        await self._assert_owner(head_user_id, project_id)
        await self.projects.set_target_enabled(
            project_id=project_id, target_id=target_id,
            enabled=enabled, platform="telegram",
        )

    async def set_schedule(
        self, *, head_user_id: int, project_id: int,
        cron_expression: str, timezone: str, enabled: bool,
    ) -> int:
        await self._assert_owner(head_user_id, project_id)
        return await self.projects.set_schedule(
            project_id=project_id, cron_expression=cron_expression,
            timezone=timezone, enabled=enabled,
        )

    async def get_ai_usage(
        self, *, head_user_id: int, project_id: int
    ) -> dict[str, Any]:
        await self._assert_owner(head_user_id, project_id)
        rules = await self.projects.get_rules(project_id=project_id)
        return {
            "usage": await self.editorial.get_monthly_usage(project_id=project_id),
            "monthly_budget_rub": rules.get("monthly_ai_budget_rub"),
        }


def build_application(settings: Settings) -> Application:
    """Build the polling application; command execution is admin-allowlisted."""
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured.")

    service = TelegramAdminService(str(settings.database_path))
    application = Application.builder().token(token).build()

    async def show_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        user = update.effective_user
        if message is not None and user is not None:
            await message.reply_text(f"Ваш Telegram ID: {user.id}")

    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        del context
        message = update.effective_message
        if message is not None:
            await message.reply_text(
                "Бот управления новостными проектами запущен. "
                "Команды: /news help. Узнать свой ID: /id."
            )

    async def news(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        user = update.effective_user
        if message is None or user is None:
            return
        if user.id not in settings.telegram_admin_id_set:
            await message.reply_text("Нет доступа к управлению news_digest.")
            return
        if not context.args:
            await message.reply_text(HELP)
            return
        try:
            response = await _dispatch(
                service, user.id, context.args[0].lower(),
                " ".join(context.args[1:]).strip(),
            )
        except (ValueError, PermissionError) as exc:
            response = f"Не удалось выполнить команду: {exc}"
        except Exception:
            logger.exception("Standalone Telegram administration command failed")
            response = "Внутренняя ошибка. Подробности записаны в журнал."
        await message.reply_text(response)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("id", show_id))
    application.add_handler(CommandHandler("news", news))
    return application
