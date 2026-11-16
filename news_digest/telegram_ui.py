"""Button-first Telegram management UI for news-digest projects.

Users navigate projects and settings with inline keyboards. Text input is requested
only for values that cannot reasonably be selected from a menu.
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters

from news_digest.telegram_service import StandaloneProjectService

logger = logging.getLogger(__name__)

MAIN = "ui:main"


def _service(context: ContextTypes.DEFAULT_TYPE) -> StandaloneProjectService:
    return context.application.bot_data["service"]


def _allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    settings = context.application.bot_data["settings"]
    admins = settings.admin_telegram_ids_set
    return bool(admins and update.effective_user and update.effective_user.id in admins)


async def _deny(update: Update) -> None:
    target = update.effective_message
    if target:
        await target.reply_text("Доступ запрещён.")


def _kb(rows):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=data) for label, data in row]
        for row in rows
    ])


def main_keyboard():
    return _kb([
        [("📁 Мои проекты", "ui:projects"), ("➕ Создать проект", "ui:create")],
        [("❔ Помощь", "ui:help")],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("news_ui_input", None)
    if not _allowed(update, context):
        await _deny(update)
        return
    await update.effective_message.reply_text(
        "👋 Добро пожаловать в News Digest!\n\n"
        "Здесь можно создавать новостные проекты, подключать RSS-источники, "
        "настраивать каналы публикации и расписание. Управление — кнопками ниже.",
        reply_markup=main_keyboard(),
    )


async def projects_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await _deny(update)
        return
    await show_projects(update, context, edit=False)


async def dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await _deny(update)
        return
    await update.effective_message.reply_text("🏠 Главное меню", reply_markup=main_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await _deny(update)
        return
    await update.effective_message.reply_text(
        "📚 <b>Управление News Digest</b>\n\n"
        "/start — главное меню\n/projects — ваши проекты\n/dashboard — главное меню\n/help — помощь\n/cancel — отменить ввод\n\n"
        "Все основные действия доступны через кнопки. Команда /news оставлена для обратной совместимости.",
        parse_mode="HTML", reply_markup=main_keyboard(),
    )


async def show_projects(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=True) -> None:
    projects = await _service(context).list_projects(head_user_id=update.effective_user.id)
    rows = [[(f"{'🟢' if p['status']=='active' else '⏸️' if p['status']=='paused' else '📝'} {p['name']}", f"ui:p:{p['id']}")] for p in projects]
    rows.append([("➕ Создать проект", "ui:create")])
    rows.append([("🏠 Главное меню", MAIN)])
    text = "📁 <b>Ваши проекты</b>\n\nВыберите проект:" if projects else "📁 <b>Ваших проектов пока нет.</b>\nСоздайте первый проект:"
    markup = _kb(rows)
    if update.callback_query and edit:
        await update.callback_query.edit_message_text(text, parse_mode="HTML", reply_markup=markup)
    else:
        await update.effective_message.reply_text(text, parse_mode="HTML", reply_markup=markup)


async def _project_menu(query, context, project_id: int) -> None:
    projects = await _service(context).list_projects(head_user_id=query.from_user.id)
    project = next((p for p in projects if p["id"] == project_id), None)
    if not project:
        await query.edit_message_text("Проект не найден.", reply_markup=_kb([[("◀️ К проектам", "ui:projects")]]))
        return
    status_label = {"draft": "Черновик", "active": "Активен", "paused": "Приостановлен"}.get(project["status"], project["status"])
    rows = [
        [("📥 Источники", f"ui:sources:{project_id}"), ("📤 Каналы", f"ui:targets:{project_id}")],
        [("📝 Редакционные правила", f"ui:rules:{project_id}")],
        [("🕒 Расписание", f"ui:schedule:{project_id}"), ("💳 Расходы AI", f"ui:usage:{project_id}")],
        [("🌐 Язык и часовой пояс", f"ui:settings:{project_id}")],
    ]
    if project["status"] == "active":
        rows.append([("⏸ Приостановить", f"ui:status:{project_id}:paused")])
    else:
        rows.append([("▶️ Активировать", f"ui:status:{project_id}:active")])
    rows += [[("◀️ К проектам", "ui:projects"), ("🏠 Меню", MAIN)]]
    await query.edit_message_text(
        f"📁 <b>{html.escape(str(project['name']))}</b>\nСтатус: {status_label}\nЯзык: {project['language']}\nЧасовой пояс: {project['timezone']}\n\nВыберите раздел:",
        parse_mode="HTML", reply_markup=_kb(rows),
    )


async def _input_prompt(query, context, kind: str, project_id: int, prompt: str) -> None:
    context.user_data["news_ui_input"] = {"kind": kind, "project_id": project_id}
    await query.edit_message_text(
        prompt + "\n\n/cancel — отменить",
        reply_markup=_kb([[("✖️ Отмена", f"ui:cancel:{project_id}")]]),
    )


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not _allowed(update, context):
        await query.edit_message_text("Доступ запрещён.")
        return
    data = query.data or ""
    user_id = query.from_user.id
    service = _service(context)
    try:
        if data == MAIN:
            await query.edit_message_text("🏠 Главное меню", reply_markup=main_keyboard())
        elif data == "ui:help":
            await query.edit_message_text("Основные действия выполняются кнопками. Для отмены текущего ввода используйте /cancel.", reply_markup=_kb([[("🏠 Главное меню", MAIN)]]))
        elif data == "ui:projects":
            await show_projects(update, context)
        elif data == "ui:create":
            context.user_data["news_ui_input"] = {"kind": "create_name"}
            await query.edit_message_text("➕ <b>Создание проекта</b>\n\nКак назвать проект? Отправьте название сообщением.\n\n/cancel — отменить", parse_mode="HTML", reply_markup=_kb([[("✖️ Отмена", "ui:cancel")]]))
        elif data == "ui:cancel" or data.startswith("ui:cancel:"):
            context.user_data.pop("news_ui_input", None)
            if data.count(":") == 2:
                await _project_menu(query, context, int(data.split(":")[2]))
            else:
                await query.edit_message_text("Ввод отменён.", reply_markup=main_keyboard())
        elif data.startswith("ui:p:"):
            await _project_menu(query, context, int(data.split(":")[2]))
        elif data.startswith("ui:status:"):
            _, _, pid, status = data.split(":")
            await service.set_project_status(head_user_id=user_id, project_id=int(pid), status=status)
            await _project_menu(query, context, int(pid))
        elif data.startswith("ui:sources:"):
            pid = int(data.split(":")[2])
            items = await service.list_sources(head_user_id=user_id, project_id=pid)
            rows = [[(f"{'🟢' if s['enabled'] else '⚪'} {s['name'] or s['url'][:28]}", f"ui:source-toggle:{pid}:{s['id']}:{'off' if s['enabled'] else 'on'}")] for s in items]
            rows += [[("➕ Добавить RSS-источник", f"ui:addsource:{pid}")], [("◀️ Назад", f"ui:p:{pid}")]]
            text = "📥 <b>Источники</b>\nНажмите на источник, чтобы изменить его состояние." if items else "📥 <b>Источников пока нет.</b>"
            await query.edit_message_text(text, parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:source-toggle:"):
            _, _, pid, sid, state = data.split(":")
            await service.set_source_enabled(head_user_id=user_id, project_id=int(pid), source_id=int(sid), enabled=state == "on")
            items = await service.list_sources(head_user_id=user_id, project_id=int(pid))
            rows = [[(f"{'🟢' if s['enabled'] else '⚪'} {s['name'] or s['url'][:28]}", f"ui:source-toggle:{pid}:{s['id']}:{'off' if s['enabled'] else 'on'}")] for s in items]
            rows += [[("➕ Добавить RSS-источник", f"ui:addsource:{pid}")], [("◀️ Назад", f"ui:p:{pid}")]]
            await query.edit_message_text("📥 <b>Источники</b>", parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:addsource:"):
            await _input_prompt(query, context, "addsource", int(data.split(":")[2]), "Отправьте RSS URL источника:")
        elif data.startswith("ui:targets:"):
            pid = int(data.split(":")[2])
            items = await service.list_targets(head_user_id=user_id, project_id=pid)
            rows = [[(f"{'🟢' if t['enabled'] else '⚪'} {t.get('title') or t['target_id']}", f"ui:target-toggle:{pid}:{t['target_id']}:{'off' if t['enabled'] else 'on'}")] for t in items]
            rows += [[("➕ Добавить канал", f"ui:addtarget:{pid}")], [("◀️ Назад", f"ui:p:{pid}")]]
            await query.edit_message_text("📤 <b>Каналы публикации</b>\nНажмите на канал, чтобы включить или выключить его." if items else "📤 <b>Каналы ещё не добавлены.</b>", parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:target-toggle:"):
            _, _, pid, target, state = data.split(":")
            await service.set_target_enabled(head_user_id=user_id, project_id=int(pid), target_id=target, enabled=state == "on")
            items = await service.list_targets(head_user_id=user_id, project_id=int(pid))
            rows = [[(f"{'🟢' if t['enabled'] else '⚪'} {t.get('title') or t['target_id']}", f"ui:target-toggle:{pid}:{t['target_id']}:{'off' if t['enabled'] else 'on'}")] for t in items]
            rows += [[("➕ Добавить канал", f"ui:addtarget:{pid}")], [("◀️ Назад", f"ui:p:{pid}")]]
            await query.edit_message_text("📤 <b>Каналы публикации</b>", parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:addtarget:"):
            await _input_prompt(query, context, "addtarget", int(data.split(":")[2]), "Отправьте @username канала или числовой ID. Бот должен иметь права администратора в канале:")
        elif data.startswith("ui:rules:"):
            pid = int(data.split(":")[2])
            rules = await service.get_rules(head_user_id=user_id, project_id=pid)
            summary = (
                f"Темы: {', '.join(rules.get('topics', [])) or 'не заданы'}\n"
                f"География: {', '.join(rules.get('geographies', [])) or 'не задана'}\n"
                f"Исключить: {', '.join(rules.get('excluded_topics', [])) or 'нет'}\n"
                f"Аудитория: {rules.get('audience', 'не задана')}\n"
                f"Стиль: {rules.get('style_guide', 'не задан')}\n"
                f"Минимальная значимость: {rules.get('min_significance', 'по умолчанию')}\n"
                f"Максимальный возраст новости: {rules.get('max_age_hours', 'по умолчанию')} ч."
            )
            summary = html.escape(summary)
            rows = [
                [("🧭 Темы", f"ui:ruleedit:{pid}:topics"), ("🌍 География", f"ui:ruleedit:{pid}:geographies")],
                [("🚫 Исключить темы", f"ui:ruleedit:{pid}:excluded_topics")],
                [("👥 Аудитория", f"ui:ruleedit:{pid}:audience"), ("✍️ Стиль", f"ui:ruleedit:{pid}:style_guide")],
                [("⭐ Значимость", f"ui:ruleedit:{pid}:min_significance"), ("🕓 Давность", f"ui:ruleedit:{pid}:max_age_hours")],
                [("◀️ Назад", f"ui:p:{pid}")],
            ]
            await query.edit_message_text("📝 <b>Редакционные правила</b>\n\n" + summary + "\n\nВыберите, что изменить:", parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:ruleedit:"):
            _, _, pid, key = data.split(":")
            prompts = {
                "topics": "Перечислите интересующие темы через запятую. Например: искусственный интеллект, экономика, космос",
                "geographies": "Перечислите страны или регионы через запятую. Например: Россия, Европа, США",
                "excluded_topics": "Перечислите темы, которые нужно исключить, через запятую.",
                "audience": "Опишите целевую аудиторию обычным текстом.",
                "style_guide": "Опишите желаемый стиль новостных публикаций.",
                "min_significance": "Укажите минимальную значимость от 0 до 100.",
                "max_age_hours": "Укажите максимальный возраст новости в часах (1–8760).",
            }
            context.user_data["news_ui_input"] = {"kind": "rule", "project_id": int(pid), "key": key}
            await query.edit_message_text(prompts[key] + "\n\n/cancel — отменить", reply_markup=_kb([[("✖️ Отмена", f"ui:cancel:{pid}")]]))
        elif data.startswith("ui:schedule:"):
            pid = int(data.split(":")[2])
            rows = [
                [("Каждые 2 часа", f"ui:set-schedule:{pid}:0 */2 * * *"), ("Каждые 4 часа", f"ui:set-schedule:{pid}:0 */4 * * *")],
                [("08:00 и 20:00", f"ui:set-schedule:{pid}:0 8,20 * * *"), ("Каждый день в 10:00", f"ui:set-schedule:{pid}:0 10 * * *")],
                [("◀️ Назад", f"ui:p:{pid}")],
            ]
            await query.edit_message_text("🕒 <b>Расписание публикаций</b>\nВыберите готовый вариант:", parse_mode="HTML", reply_markup=_kb(rows))
        elif data.startswith("ui:set-schedule:"):
            _, _, pid, cron = data.split(":", 3)
            projects = await service.list_projects(head_user_id=user_id)
            project = next((item for item in projects if item["id"] == int(pid)), None)
            if project is None:
                raise ValueError("Проект не найден.")
            timezone = project["timezone"]
            await service.set_schedule(head_user_id=user_id, project_id=int(pid), cron_expression=cron, timezone=timezone, enabled=True)
            await query.edit_message_text(f"✅ Расписание сохранено ({html.escape(timezone)}).", reply_markup=_kb([[("◀️ К проекту", f"ui:p:{pid}")]]))
        elif data.startswith("ui:settings:"):
            pid = int(data.split(":")[2])
            await query.edit_message_text("🌐 <b>Настройки проекта</b>\n\nВыберите язык:", parse_mode="HTML", reply_markup=_kb([[("Русский", f"ui:lang:{pid}:ru"), ("English", f"ui:lang:{pid}:en")], [("◀️ Назад", f"ui:p:{pid}")]]))
        elif data.startswith("ui:lang:"):
            _, _, pid, lang = data.split(":")
            context.user_data["news_ui_input"] = {"kind": "timezone", "project_id": int(pid), "language": lang}
            await query.edit_message_text("Отправьте часовой пояс, например Europe/Moscow или Europe/Berlin:")
        elif data.startswith("ui:usage:"):
            pid = int(data.split(":")[2])
            report = await service.get_ai_usage(head_user_id=user_id, project_id=pid)
            usage, budget = report["usage"], report["monthly_budget_rub"]
            budget_text = f"{budget:.2f} ₽" if budget is not None else "не задан"
            await query.edit_message_text(
                f"💳 <b>Расходы AI за месяц</b>\nСтоимость: {usage['cost']:.4f} ₽ из {budget_text}\nЗапросов: {usage['requests']}\nТокенов: {usage['total_tokens']}",
                parse_mode="HTML", reply_markup=_kb([[("◀️ Назад", f"ui:p:{pid}")]]),
            )
        else:
            await query.edit_message_text("Неизвестное действие.", reply_markup=_kb([[("🏠 Меню", MAIN)]]))
    except (ValueError, PermissionError) as exc:
        await query.edit_message_text(f"Не удалось выполнить действие: {exc}", reply_markup=_kb([[("🏠 Меню", MAIN)]]))
    except Exception:
        logger.exception("News digest inline UI action failed")
        await query.edit_message_text("Внутренняя ошибка. Подробности записаны в журнал.", reply_markup=_kb([[("🏠 Меню", MAIN)]]))


async def text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pending = context.user_data.get("news_ui_input")
    if not pending:
        return
    if not _allowed(update, context):
        await _deny(update)
        return
    value = (update.effective_message.text or "").strip()
    if value.lower() in {"/cancel", "отмена"}:
        context.user_data.pop("news_ui_input", None)
        await update.effective_message.reply_text("Действие отменено.", reply_markup=main_keyboard())
        return
    service = _service(context)
    user_id = update.effective_user.id
    kind = pending["kind"]
    try:
        if kind == "create_name":
            name = value.strip()
            if len(name) < 2 or len(name) > 80:
                raise ValueError("Название должно содержать от 2 до 80 символов.")
            slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
            if not slug:
                slug = f"project-{user_id}-{int(datetime.now().timestamp())}"
            project_id = await service.create_project(head_user_id=user_id, slug=slug[:48], name=name)
            context.user_data.pop("news_ui_input", None)
            await update.effective_message.reply_text(f"✅ Проект «{name}» создан. Настройте его через меню:", reply_markup=_kb([[("Открыть проект", f"ui:p:{project_id}")], [("📁 К проектам", "ui:projects")]]))
            return
        pid = int(pending["project_id"])
        if kind == "addsource":
            if not value.startswith(("https://", "http://")):
                raise ValueError("Нужна полная ссылка RSS, начинающаяся с http:// или https://.")
            source_id = await service.add_source(head_user_id=user_id, project_id=pid, url=value)
            context.user_data.pop("news_ui_input", None)
            await update.effective_message.reply_text(f"✅ RSS-источник добавлен (ID {source_id}).", reply_markup=_kb([[("📥 К источникам", f"ui:sources:{pid}")], [("◀️ К проекту", f"ui:p:{pid}")]]))
            return
        if kind == "addtarget":
            if not (value.startswith("@") or value.startswith("-100") or value.lstrip("-").isdigit()):
                raise ValueError("Укажите @username или числовой ID канала.")
            target_id = value
            target_pk = await service.add_target(head_user_id=user_id, project_id=pid, target_id=target_id, enabled=False)
            context.user_data.pop("news_ui_input", None)
            await update.effective_message.reply_text(f"✅ Канал добавлен (ID записи {target_pk}), пока выключен. Включите его кнопкой после проверки прав бота.", reply_markup=_kb([[("📤 К каналам", f"ui:targets:{pid}")], [("◀️ К проекту", f"ui:p:{pid}")]]))
            return
        if kind == "rule":
            key = pending["key"]
            await service._owned(user_id, pid)
            rules = await service.projects.get_rules(project_id=pid)
            if key in {"topics", "geographies", "excluded_topics"}:
                rules[key] = [part.strip() for part in value.split(",") if part.strip()]
            elif key in {"min_significance", "max_age_hours"}:
                try:
                    rules[key] = int(value)
                except ValueError as exc:
                    raise ValueError("Введите целое число.") from exc
            else:
                rules[key] = value
            await service.save_rules(head_user_id=user_id, project_id=pid, rules=rules)
            context.user_data.pop("news_ui_input", None)
            await update.effective_message.reply_text("✅ Правило сохранено.", reply_markup=_kb([[("📝 К правилам", f"ui:rules:{pid}")], [("◀️ К проекту", f"ui:p:{pid}")]]))
            return
        if kind == "timezone":
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            try:
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError("Неизвестный часовой пояс. Пример: Europe/Moscow.")
            await service.update_project_settings(head_user_id=user_id, project_id=pid, language=pending["language"], timezone=value)
            context.user_data.pop("news_ui_input", None)
            await update.effective_message.reply_text("✅ Настройки сохранены.", reply_markup=_kb([[("◀️ К проекту", f"ui:p:{pid}")]]))
            return
    except (ValueError, PermissionError, json.JSONDecodeError) as exc:
        await update.effective_message.reply_text(f"Не удалось сохранить: {exc}\nПопробуйте ещё раз или /cancel.")
    except Exception:
        logger.exception("News digest text input failed")
        await update.effective_message.reply_text("Внутренняя ошибка. Попробуйте позже или /cancel.")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update, context):
        await _deny(update)
        return
    context.user_data.pop("news_ui_input", None)
    await update.effective_message.reply_text("Ввод отменён.", reply_markup=main_keyboard())


def register_ui(application) -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("projects", projects_command))
    application.add_handler(CommandHandler("dashboard", dashboard))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("cancel", cancel))
    application.add_handler(CallbackQueryHandler(callback, pattern=r"^ui:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_input))
