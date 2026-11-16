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

Projects start in `draft` and are processed only after their status is set to `active`. Use `ProjectRepository` to manage per-project RSS sources, editorial rules, Telegram targets and cron schedules. Cron schedules are evaluated in each project's IANA timezone by `news-digest --scheduler`; `--once` remains a manual run of all active projects.

## KontentFabrik integration

The optional `KontentFabrikAdapter` reads the existing `kf_users`, `user_bindings` and `workers` registry tables using a read-only PostgreSQL connection. It resolves the head-bot Telegram identity to the `news_digest` worker user ID; project data and schedules remain in this worker's own SQLite database. Configure `KONTENTFABRIK_DATABASE_URL` with a read-only database role. A `news_digest` worker and user binding must first be registered in KontentFabrik. This repository does not modify KontentFabrik or its database schema.
