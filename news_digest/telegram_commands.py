"""Command parser and dispatcher shared by Telegram entry points."""

from __future__ import annotations

import json
from typing import Any


HELP = """Управление новостными проектами:
/news projects
/news create slug | Название проекта
/news status ID | active или paused
/news settings ID | language | timezone
/news sources ID
/news addsource ID | RSS URL | Название источника | shared/project
/news source-toggle ID | SOURCE_ID | on/off
/news rules ID | JSON с настройками
/news targets ID
/news addtarget ID | @channel или -100... | Название
/news target-toggle ID | @channel или -100... | on/off
/news schedule ID | cron | Europe/Moscow | on/off
/news usage ID
/news help

Проект создаётся в статусе draft. Для обработки переведите его в active.
"""


async def dispatch(service: Any, user_id: int, command: str, raw: str) -> str:
    if command in {"help", "start"}:
        return HELP
    if command == "projects":
        projects = await service.list_projects(head_user_id=user_id)
        if not projects:
            return "Проектов пока нет. Создайте первый: /news create slug | Название"
        return "\n".join(
            f'#{p["id"]} {p["name"]} — {p["status"]} '
            f'({p["language"]}, {p["timezone"]})' for p in projects
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
    if command == "settings":
        project_text, language, timezone = _fields(raw, 3)
        await service.update_project_settings(
            head_user_id=user_id, project_id=int(project_text),
            language=language, timezone=timezone,
        )
        return f"Настройки проекта #{project_text}: язык {language}, часовой пояс {timezone}."
    if command == "sources":
        (project_text,) = _fields(raw, 1)
        sources = await service.list_sources(
            head_user_id=user_id, project_id=int(project_text)
        )
        if not sources:
            return "Источников пока нет."
        return "\n".join(
            f'#{s["id"]} {s["name"] or s["url"]} — '
            f'{"включён" if s["enabled"] else "выключен"}\n{s["url"]}' for s in sources
        )
    if command == "addsource":
        fields = _optional_fields(raw, 2, 4)
        project_text, url = fields[:2]
        name = fields[2] if len(fields) >= 3 else None
        mode = fields[3].lower() if len(fields) == 4 else "project"
        if mode not in {"shared", "project"}:
            raise ValueError("Режим источника должен быть shared или project.")
        source_id = await service.add_source(
            head_user_id=user_id, project_id=int(project_text), url=url,
            name=name, source_mode=mode,
        )
        return f"Источник добавлен к проекту #{project_text} (ID источника {source_id})."
    if command == "source-toggle":
        project_text, source_text, enabled_text = _fields(raw, 3)
        await service.set_source_enabled(
            head_user_id=user_id, project_id=int(project_text),
            source_id=int(source_text), enabled=_as_bool(enabled_text),
        )
        return f"Источник #{source_text}: {'включён' if _as_bool(enabled_text) else 'выключен'}."
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
        fields = _optional_fields(raw, 2, 3)
        project_text, target_id = fields[:2]
        title = fields[2] if len(fields) == 3 else None
        target_pk = await service.add_target(
            head_user_id=user_id, project_id=int(project_text),
            target_id=target_id, title=title, enabled=False,
        )
        return f"Канал добавлен к проекту #{project_text} (ID {target_pk}); пока выключен."
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
            f"Расход RouterAI за текущий месяц, проект #{project_text}:\n"
            f"Стоимость: {usage['cost']:.4f} ₽ из {budget_text}\n"
            f"Запросов: {usage['requests']}\n"
            f"Токены: вход {usage['input_tokens']} (кэш {usage['cached_input_tokens']}), "
            f"выход {usage['output_tokens']}, всего {usage['total_tokens']}\n"
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
