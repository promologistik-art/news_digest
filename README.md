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
```

`--test-ai` sends one short request to RouterAI and reports the returned model, provider (if supplied) and token usage. It does not publish anything.

The worker is safe by default: Telegram publishing remains disabled until explicitly configured.
