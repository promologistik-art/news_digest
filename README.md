# news_digest

Multi-project news collection, editorial processing and Telegram publishing worker.

## Architecture

- Independent worker deployed on server `swe`, separate from ZenDigest.
- RouterAI is the initial AI gateway; default model: `deepseek/deepseek-v4.1-flash`.
- API credentials are supplied only through environment variables.
- Shared article collection and deduplication, followed by project-specific relevance and editorial processing.
- Independent project settings, sources, schedules, destinations, queues and publication history.
- SQLite for the first deployable iteration, with a repository layer designed to allow PostgreSQL later.
- Standalone Telegram administration runs in the same process as the scheduler; it does not require KontentFabrik.

## Development

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `ROUTERAI_API_KEY` and `TELEGRAM_BOT_TOKEN` in the local `.env`. Never commit `.env` or paste secrets into chat.

## Production start (PixiePandora)

The repository root `main.py` is the production entry point. Configure PixiePandora to run:

```bash
python main.py
```

It starts both:
- the timezone-aware project scheduler (checks due schedules every 20 seconds);
- the standalone Telegram bot, which accepts `/news` commands.

The process stays alive. It does not perform only one collection pass and exit.

Required environment:
- `ROUTERAI_API_KEY` — RouterAI key;
- `TELEGRAM_BOT_TOKEN` — token of the bot that will receive admin commands and optionally publish posts;
- `TELEGRAM_ADMIN_IDS` — comma-separated numeric Telegram user IDs allowed to manage projects.

To find your numeric Telegram ID, open the bot and send `/id`. Add the returned number to `TELEGRAM_ADMIN_IDS` in PixiePandora and restart/redeploy the container. `/id` is intentionally available before the allowlist is configured; all management commands remain blocked until an ID is allowlisted.

Publishing is separately controlled by `TELEGRAM_PUBLISHING_ENABLED=false` by default. Keep it false while configuring projects and destinations. Enable it only when you are ready for approved posts to be sent to configured channels.

## Telegram commands

Send `/news help` to the bot.

| Command | Purpose |
|---|---|
| `/news projects` | List your projects |
| `/news create slug | Project name` | Create a project (starts as draft) |
| `/news status ID | active/paused/draft/archived` | Change project status |
| `/news settings ID | language | timezone` | Set language and IANA timezone |
| `/news sources ID` | List RSS sources |
| `/news addsource ID | RSS URL | Name | shared/project` | Add an RSS source |
| `/news source-toggle ID | SOURCE_ID | on/off` | Enable or disable a source |
| `/news rules ID | JSON` | Save editorial rules |
| `/news targets ID` | List Telegram destinations |
| `/news addtarget ID | @channel | Title` | Add a destination (disabled by default) |
| `/news target-toggle ID | @channel | on/off` | Enable or disable a destination |
| `/news schedule ID | cron | Europe/Moscow | on/off` | Configure a project schedule |
| `/news usage ID` | Show current-month AI usage and budget |

Example setup:

```text
/news create cinema | Кино и сериалы
/news addsource 1 | https://example.com/rss.xml | Example News | shared
/news rules 1 | {"topics":["кино","сериалы"],"geographies":["Россия","Мир"],"excluded_topics":["реклама"],"min_significance":60,"max_age_hours":48,"monthly_ai_budget_rub":50}
/news addtarget 1 | @my_channel | Мой канал
/news target-toggle 1 | @my_channel | on
/news schedule 1 | 0 */2 * * * | Europe/Moscow | on
/news status 1 | active
```

The bot checks Telegram numeric IDs against `TELEGRAM_ADMIN_IDS` before running management commands. Project records are also scoped to the Telegram user who created them.

## Manual maintenance commands

```bash
news-digest --check-config
news-digest --init-db
news-digest --test-ai
news-digest --once
news-digest --scheduler
```

- `--test-ai` sends one short request to RouterAI and reports the returned model and token usage. It does not publish anything.
- `--once` performs one processing cycle for all active projects.
- `--scheduler` runs only the schedule worker, without Telegram command polling.
- `python main.py` is the combined production mode.

## Project scheduling and AI budgets

Projects start in `draft` and are processed only after their status is set to `active`. RSS sources can be `shared` (fetched once for all subscribed active projects) or `project` (fetched for one project). Cron schedules are evaluated in each project's IANA timezone.

Editorial rules accept `monthly_ai_budget_rub` to cap estimated RouterAI spend for an individual project. The worker reserves estimated request cost before sending each assessment/draft request and settles the reservation using returned token usage. Configure `AI_INPUT_PRICE_PER_MILLION`, `AI_OUTPUT_PRICE_PER_MILLION`, `AI_CACHE_READ_PRICE_PER_MILLION` and `AI_COST_CURRENCY` to match the active RouterAI model's rates. Cached prompt tokens are billed at the separate cache-read rate when RouterAI reports them. If RouterAI does not return token counts, the worker records the conservative request estimate and marks it as estimated.

## KontentFabrik integration

An optional `KontentFabrikAdapter` remains available for a future integration. It reads the existing `kf_users`, `user_bindings` and `workers` registry tables using a read-only PostgreSQL connection. It is not required for the standalone Telegram bot, and this repository does not modify KontentFabrik or its database schema.

## Server deployment

A dedicated systemd unit template and a deployment checklist for `swe` are in [`deploy/`](deploy/README.md). These files are templates; no server commands have been executed.
