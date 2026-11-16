# news_digest

Самостоятельный Telegram-бот для сбора, редакционной обработки и публикации новостей по независимым проектам.

## Runtime

Один процесс одновременно запускает polling собственного Telegram-бота, команду управления /news и планировщик проектных расписаний. Данные хранятся в собственной SQLite-базе. KontentFabrik не требуется для запуска; его адаптер остаётся отдельной опциональной интеграцией на будущее.

## Configuration

Python 3.11+. Установить зависимости: python -m pip install -e ".[dev]".

Заполнить .env:
- TELEGRAM_BOT_TOKEN — токен отдельного бота.
- ADMIN_TELEGRAM_IDS — числовые Telegram ID администраторов через запятую.
- ROUTERAI_API_KEY — ключ RouterAI.
- DATABASE_URL — SQLite URL.

Если ADMIN_TELEGRAM_IDS пуст, команды управления отвечают отказом. Автоматического назначения первого пользователя администратором нет.

## Commands

CLI: news-digest --check-config, --init-db, --test-ai, --once, --scheduler или --bot.

Для PixiePandora entrypoint python main.py запускает --bot: Telegram polling и планировщик в одном постоянно работающем процессе. Для systemd используется тот же режим news-digest --bot.

В Telegram доступна команда /news help. Основные подкоманды: projects, create, status, settings, sources, addsource, source-toggle, rules, targets, addtarget, target-toggle, schedule и usage. Доступ ограничен ADMIN_TELEGRAM_IDS; сервис дополнительно проверяет владельца каждого проекта в собственной SQLite-базе. Проекты создаются в draft; для обработки их нужно перевести в active.

## Publishing safety

TELEGRAM_PUBLISHING_ENABLED=false по умолчанию. До включения отправки нужно проверить права бота в тестовом канале и убедиться, что target назначен правильному проекту. Очередь хранит доставку отдельно по каждому каналу, чтобы повторный запуск не отправлял успешно доставленные публикации повторно.

Планировщик продолжает работу после ошибки отдельного polling-цикла и пишет traceback в лог.

## Future KontentFabrik integration

KONTENTFABRIK_DATABASE_URL и адаптер в news_digest/integrations/kontentfabrik/ предназначены только для будущей интеграции. Самостоятельный Telegram runtime не подключается к реестру KontentFabrik и не требует его базы. Этот репозиторий не изменяет KontentFabrik.
