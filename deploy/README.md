# Deployment on swe

This is a deployment recipe only. It has not been executed on the server.

## Target layout

- Application: `/opt/news_digest/app`
- Virtual environment: `/opt/news_digest/venv`
- Environment file: `/opt/news_digest/.env`
- SQLite database and writable data: `/opt/news_digest/data`
- systemd unit: `/etc/systemd/system/news-digest.service`

Run the worker as a dedicated unprivileged `newsdigest` user. Do not reuse the ZenDigest working directory, virtual environment, database, environment file or service.

## First installation

1. Create the `newsdigest` system user and group.
2. Clone `https://github.com/promologistik-art/news_digest` into `/opt/news_digest/app`.
3. Create `/opt/news_digest/venv` with Python 3.11 and install the package:
   `/opt/news_digest/venv/bin/pip install -e /opt/news_digest/app`.
4. Create `/opt/news_digest/data`, owned by `newsdigest:newsdigest`.
5. Copy `.env.example` to `/opt/news_digest/.env`, edit it locally on the server and set secrets there. Never commit the production `.env`.
6. Set an absolute SQLite URL:
   `DATABASE_URL=sqlite:////opt/news_digest/data/news_digest.sqlite3`.
7. Keep `TELEGRAM_PUBLISHING_ENABLED=false` until the bot token, bot channel permissions and project targets have been verified.
8. Initialize the database:
   `cd /opt/news_digest/app && /opt/news_digest/venv/bin/news-digest --init-db`.
9. Check configuration and RouterAI connectivity:
   `news-digest --check-config` and `news-digest --test-ai`.
10. Install this unit as `/etc/systemd/system/news-digest.service`, then run `systemctl daemon-reload`, `systemctl enable --now news-digest.service`.

## Operations

- Status: `systemctl status news-digest.service`
- Logs: `journalctl -u news-digest.service -f`
- Restart after code/config changes: `systemctl restart news-digest.service`
- Stop: `systemctl stop news-digest.service`

For an application update, pull the intended commit in `/opt/news_digest/app`, install the updated package in the same virtual environment, then restart the service. Back up the SQLite database before schema-changing updates.

## Before enabling Telegram delivery

- Verify the bot is administrator in every configured target channel.
- Verify each target belongs to the intended project.
- Start with a private test channel and a single test project.
- Confirm photo delivery, text fallback when no safe image exists, caption length, retries and per-target idempotency.
- Only then set `TELEGRAM_PUBLISHING_ENABLED=true` and restart the service.

## Safety boundaries

This service runs only `news_digest`. It does not replace or restart ZenDigest, TG2TG1, KontentFabrik or any other systemd unit. The service file uses a dedicated user and only grants write access to `/opt/news_digest/data`.
