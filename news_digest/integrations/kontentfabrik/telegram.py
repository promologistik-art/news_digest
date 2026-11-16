"""Telegram command handlers that can be mounted by the KontentFabrik head bot."""

from __future__ import annotations

import json
import logging

from telegram import Update
from telegram.ext import CommandHandler, ContextTypes

from news_digest.integrations.kontentfabrik.adapter import KontentFabrikError
from news_digest.integrations.kontentfabrik.service import (
    KontentFabrikProjectService,
)

logger = logging.getLogger(__name__)

HELP = """Управление новостными проектами:
/news projects
/news create slug | Название проекта
/news status ID | active или paused
/news sources ID
/news addsource ID | RSS URL | Название источника | shared/project
/news source-toggle ID | SOURCE_ID | on/off
/news rules ID | JSON с настройками
/news targets ID
/news addtarget ID | @channel или -100... | Название
/news target-toggle ID | @channel или -100... | on/off
/news schedule ID | cron | Europe/Moscow | on/off
/news usage ID

Проект создаётся в статусе draft. Для обработки переведите его в active.
Пример правил: {"topics":["кино","книги"],"geographies":["Россия","Мир"],
"excluded_topics":["реклама"],"min_significance":60,"max_age_hours":48}.
Расписание задаётся в часовом поясе проекта; публикация дополнительно зависит
от настроек доставки worker.
"""


def build_handlers(service: KontentFabrikProjectService) -> list[CommandHandler]:
    """Return handlers for registration in the KontentFabrik Telegram application."""

    async def handle_news(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        user = update.effective_user
        message = update.effective_message
        if user is None or message is None:
            return
        if not context.args:
            await message.reply_text(HELP)
            return

        command = context.args[0].lower()
        raw = " ".join(context.args[1:]).strip()
        try:
            response = await _dispatch(service, user.id, command, raw)
        except (ValueError, PermissionError, KontentFabrikError) as exc:
            response = f"Не удалось выполнить команду: {exc}"
        except Exception:
            logger.exception("KontentFabrik news management command failed")
            response = "Внутренняя ошибка. Команда не выполнена; подробности записаны в журнал."
        await message.reply_text(response)

    return [CommandHandler("news", handle_news)]


async def _dispatch(
    service: KontentFabrikProjectService, user_id: int, command: str, raw: str
) -> str:
    if command in {"help", "start"}:
        return HELP
    if command == "projects":
        projects = await service.list_projects(head_user_id=user_id)
        if not projects:
            return "Проектов пока нет. Создайте первый: /news create slug | Название"
        return "\n".join(
            f'#{p["id"]} {p["name"]} — {p["status"]} '
            f'({p["language"]}, {p["timezone"]})'
            for p in projects
        )

    if command == "create":
        slug, name = _fields(raw, 2)
        project_id = await service.create_project(
            head_user_id=user_id, slug=slug, name=name
        )
        return f"Проект «{name}» создан (ID {project_id}), статус draft."

    if command == "status":
        project_text, status = _fields(raw, 2)
        await service.set_project_status(
            head_user_id=user_id, project_id=int(project_text), status=status.lower()
        )
        return f"Статус проекта #{project_text}: {status.lower()}."

    if command == "sources":
        (project_text,) = _fields(raw, 1)
        sources = await service.list_sources(
            head_user_id=user_id, project_id=int(project_text)
        )
        if not sources:
            return "Источников пока нет."
        return "\n".join(
            f'#{s["id"]} {s["name"] or s["url"]} — '
            f'{"включён" if s["enabled"] else "выключен"}\n{s["url"]}'
            for s in sources
        )

    if command == "addsource":
        source_fields = _optional_fields(raw, 2, 4)
        project_text, url = source_fields[:2]
        name = source_fields[2] if len(source_fields) >= 3 else None
        source_mode = source_fields[3].lower() if len(source_fields) == 4 else "project"
        if source_mode not in {"shared", "project"}:
            raise ValueError("Режим источника должен быть shared или project.")
        source_id = await service.add_source(
            head_user_id=user_id, project_id=int(project_text), url=url,
            name=name, source_mode=source_mode,
        )
        mode_label = "общий" if source_mode == "shared" else "индивидуальный"
        return (
            f"Источник добавлен к проекту #{project_text} как {mode_label} "
            f"(ID источника {source_id})."
        )

    if command == "source-toggle":
        project_text, source_text, enabled_text = _fields(raw, 3)
        enabled = _as_bool(enabled_text)
        await service.set_source_enabled(
            head_user_id=user_id, project_id=int(project_text),
            source_id=int(source_text), enabled=enabled,
        )
        return f"Источник #{source_text}: {'включён' if enabled else 'выключен'}."

    if command == "rules":
        project_text, json_text = _fields(raw, 2, split_once=True)
        rules = json.loads(json_text)
        if not isinstance(rules, dict):
            raise ValueError("Настройки должны быть JSON-объектом.")
        await service.save_rules(
            head_user_id=user_id, project_id=int(project_text), rules=rules
        )
        return f"Редакционные настройки проекта #{project_text} сохранены."

    if command == "targets":
        (project_text,) = _fields(raw, 1)
        targets = await service.list_targets(
            head_user_id=user_id, project_id=int(project_text)
        )
        if not targets:
            return "Каналы пока не добавлены."
        return "\n".join(
            f'{t["target_id"]} — {"включён" if t["enabled"] else "выключен"}'
            for t in targets
        )

    if command == "addtarget":
        target_fields = _optional_fields(raw, 2, 3)
        project_text, target_id = target_fields[:2]
        title = target_fields[2] if len(target_fields) == 3 else None
        target_pk = await service.add_target(
            head_user_id=user_id, project_id=int(project_text),
            target_id=target_id, title=title, enabled=False,
        )
        return (
            f"Канал добавлен к проекту #{project_text} (ID {target_pk}), "
            "но пока выключен. Включите его командой target-toggle."
        )

    if command == "target-toggle":
        project_text, target_id, enabled_text = _fields(raw, 3)
        enabled = _as_bool(enabled_text)
        await service.set_target_enabled(
            head_user_id=user_id, project_id=int(project_text),
            target_id=target_id, enabled=enabled,
        )
        return f"Канал {target_id}: {'включён' if enabled else 'выключен'}."

    if command == "schedule":
        project_text, cron_expression, timezone, enabled_text = _fields(raw, 4)
        schedule_id = await service.set_schedule(
            head_user_id=user_id, project_id=int(project_text),
            cron_expression=cron_expression, timezone=timezone,
            enabled=_as_bool(enabled_text),
        )
        return f"Расписание #{schedule_id} сохранено для проекта #{project_text}."

    if command == "usage":
        (project_text,) = _fields(raw, 1)
        report = await service.get_ai_usage(
            head_user_id=user_id, project_id=int(project_text)
        )
        usage = report["usage"]
        budget = report["monthly_budget_rub"]
        budget_text = f"{budget:.2f} ₽" if budget is not None else "не задан"
        return (
            f"Расход RouterAI за текущий месяц, проект #{project_text}:\\n"
            f"Стоимость: {usage['cost']:.4f} ₽ из {budget_text}\\n"
            f"Запросов: {usage['requests']}\\n"
            f"Токены: вход {usage['input_tokens']}, выход {usage['output_tokens']}, "
            f"всего {usage['total_tokens']}\\n"
            f"Запросов с оценочной стоимостью: {usage['estimated_requests']}"
        )

    return HELP


def _fields(raw: str, count: int, *, split_once: bool = False) -> list[str]:
    parts = raw.split("|", maxsplit=1 if split_once else count - 1)
    values = [part.strip() for part in parts]
    if len(values) != count or any(not value for value in values):
        raise ValueError("Проверьте формат команды. Пример: /news help")
    return values


def _optional_fields(raw: str, minimum: int, maximum: int) -> list[str]:
    values = [part.strip() for part in raw.split("|", maxsplit=maximum - 1)]
    if not minimum <= len(values) <= maximum or any(not value for value in values):
        raise ValueError("Проверьте формат команды. Пример: /news help")
    return values


def _as_bool(value: str) -> bool:
    normalized = value.lower()
    if normalized in {"on", "вкл", "true", "1"}:
        return True
    if normalized in {"off", "выкл", "false", "0"}:
        return False
    raise ValueError("Укажите on или off.")
