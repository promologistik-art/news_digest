"""Standalone Telegram bot runtime for news-digest."""

from __future__ import annotations

import asyncio
import logging

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from news_digest.config import Settings
from news_digest.scheduling.service import ProjectScheduler
from news_digest.storage.database import Database
from news_digest.storage.editorial_repository import EditorialRepository
from news_digest.storage.project_repository import ProjectRepository
from news_digest.telegram_service import StandaloneProjectService
from news_digest.telegram_commands import HELP, dispatch

logger = logging.getLogger(__name__)



async def _news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    message = update.effective_message
    if user is None or message is None:
        return

    settings: Settings = context.application.bot_data["settings"]
    admins = settings.telegram_admin_ids_set
    if not admins:
        await message.reply_text(
            "Команды отключены: в окружении бота не задан ADMIN_TELEGRAM_IDS."
        )
        return
    if user.id not in admins:
        await message.reply_text("Доступ запрещён.")
        return

    if not context.args or context.args[0].lower() in {"help", "start"}:
        await message.reply_text(HELP)
        return

    command = context.args[0].lower()
    raw = " ".join(context.args[1:]).strip()
    try:
        service: StandaloneProjectService = context.application.bot_data["service"]
        response = await dispatch(service, user.id, command, raw)
    except (ValueError, PermissionError) as exc:
        response = f"Не удалось выполнить команду: {exc}"
    except Exception:
        logger.exception("Standalone /news command failed")
        response = "Внутренняя ошибка. Подробности записаны в журнал."
    await message.reply_text(response)


async def _post_init(application: Application) -> None:
    settings: Settings = application.bot_data["settings"]
    await Database(settings.database_path).initialize()
    await application.bot.set_my_commands(
        [BotCommand("news", "Управление новостными проектами")]
    )
    application.bot_data["scheduler_task"] = asyncio.create_task(
        ProjectScheduler(settings).run_forever(),
        name="news-digest-project-scheduler",
    )
    logger.info("Standalone Telegram bot and project scheduler initialized")


async def _post_shutdown(application: Application) -> None:
    task = application.bot_data.get("scheduler_task")
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


def run_bot(settings: Settings) -> None:
    token = settings.telegram_bot_token.get_secret_value()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty; standalone bot cannot start.")
    projects = ProjectRepository(settings.database_path)
    service = StandaloneProjectService(
        projects, EditorialRepository(settings.database_path)
    )
    application = (
        Application.builder()
        .token(token)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["service"] = service
    application.add_handler(CommandHandler("news", _news_command))
    logger.info("Starting standalone news-digest Telegram polling")
    application.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
        close_loop=True,
    )
