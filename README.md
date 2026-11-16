# news_digest

Multi-project news collection, editorial processing and Telegram publishing worker.

## Architecture

- Independent worker deployed on server `swe`, separate from ZenDigest.
- RouterAI is the initial AI gateway; default model: `deepseek/deepseek-v4.1-flash`.
- API credentials are supplied only through environment variables.
- Shared article collection and deduplication, followed by project-specific relevance and editorial processing.
- Independent project settings, sources, schedules, destinations, queues and publication history.
- SQLite for the first deployable iteration, with a repository layer designed to allow PostgreSQL later.

## Development

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

Set `ROUTERAI_API_KEY` in the local `.env`. Never commit `.env` or paste the key into chat.

## Initial commands

```bash
news-digest --check-config
news-digest --init-db
news-digest --test-ai
news-digest --once
news-digest --scheduler
```

`--test-ai` sends one short request to RouterAI and reports the returned model, provider (if supplied) and token usage. It does not publish anything.

The worker is safe by default: Telegram publishing remains disabled until explicitly configured.

## Project scheduling and management

Projects start in `draft` and are processed only after their status is set to `active`. Use `ProjectRepository` to manage per-project RSS sources, editorial rules, Telegram targets and cron schedules. RSS sources can be `shared` (fetched once for all subscribed active projects) or `project` (fetched for one project). Cron schedules are evaluated in each project's IANA timezone by `news-digest --scheduler`; `--once` remains a manual run of all active projects.

Editorial rules accept `monthly_ai_budget_rub` to cap estimated RouterAI spend for an individual project. The worker reserves estimated request cost before sending each assessment/draft request and settles the reservation using returned token usage. Configure `AI_INPUT_PRICE_PER_MILLION`, `AI_OUTPUT_PRICE_PER_MILLION`, `AI_CACHE_READ_PRICE_PER_MILLION` and `AI_COST_CURRENCY` to match the active RouterAI model's rates. Cached prompt tokens are billed at the separate cache-read rate when RouterAI reports them. If RouterAI does not return token counts, the worker records the conservative request estimate and marks it as estimated. In the KontentFabrik head bot, `/news usage PROJECT_ID` reports the current month's project usage.

## KontentFabrik integration

The optional `KontentFabrikAdapter` reads the existing `kf_users`, `user_bindings` and `workers` registry tables using a read-only PostgreSQL connection. It resolves the head-bot Telegram identity to the `news_digest` worker user ID; project data and schedules remain in this worker's own SQLite database. Configure `KONTENTFABRIK_DATABASE_URL` with a read-only database role. A `news_digest` worker and user binding must first be registered in KontentFabrik. This repository does not modify KontentFabrik or its database schema.


### Mounting management commands in KontentFabrik

The handlers are implemented in this repository, but they are not active in the running KontentFabrik bot until its application registers them. The host-side change is intentionally not included here.

Install this project in the head-bot environment and register the handlers during application startup:

```python
from news_digest.config import Settings
from news_digest.integrations.kontentfabrik import (
    KontentFabrikAdapter,
    KontentFabrikProjectService,
    build_handlers,
)
from news_digest.storage.project_repository import ProjectRepository

settings = Settings()
adapter = KontentFabrikAdapter(
    settings.kontentfabrik_database_url.get_secret_value()
)
service = KontentFabrikProjectService(
    adapter,
    ProjectRepository(settings.database_path),
)
application.add_handlers(build_handlers(service))
```

The head bot needs a read-only PostgreSQL role for the KontentFabrik registry and write access to the worker's own SQLite data directory. Do not give the adapter write access to the KontentFabrik database. The binding must already exist for the `news_digest` worker. Available commands are shown by `/news help`; project access is checked against the resolved worker-user binding on every operation.


## Server deployment

A dedicated systemd unit template and a deployment checklist for `swe` are in [`deploy/`](deploy/README.md). The unit runs only `news_digest` under its own unprivileged account and uses an isolated application directory, virtual environment, environment file and SQLite data directory. These files are templates; no server commands have been executed.
