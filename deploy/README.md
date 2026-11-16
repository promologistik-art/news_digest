# Deployment on swe

Deployment template only; no server commands have been executed from this repository.

## Runtime layout

- Application: /opt/news_digest/app
- Virtual environment: /opt/news_digest/venv
- Environment file: /opt/news_digest/.env
- SQLite database: /opt/news_digest/data/news_digest.sqlite3
- systemd unit: /etc/systemd/system/news-digest.service

Run under a dedicated unprivileged newsdigest user. Do not reuse ZenDigest directories, databases, environment files or service units.

## First installation

1. Create the newsdigest system user and group.
2. Clone this repository into /opt/news_digest/app.
3. Create the virtual environment and install dependencies:
   `/opt/news_digest/venv/bin/python -m pip install -r requirements.txt`.
4. Create /opt/news_digest/data, owned by newsdigest:newsdigest.
5. Copy .env.example to /opt/news_digest/.env.
6. Set an absolute SQLite URL, for example sqlite:////opt/news_digest/data/news_digest.sqlite3.
7. Set TELEGRAM_BOT_TOKEN, numeric ADMIN_TELEGRAM_IDS and ROUTERAI_API_KEY in the environment file. Never commit secrets.
8. Keep TELEGRAM_PUBLISHING_ENABLED=false until test delivery has been verified.
9. Initialize the database with `/opt/news_digest/venv/bin/python -m news_digest.cli --init-db`.
10. Check configuration with `/opt/news_digest/venv/bin/python -m news_digest.cli --check-config`; optionally test RouterAI with `/opt/news_digest/venv/bin/python -m news_digest.cli --test-ai`.
11. Install deploy/news-digest.service, then run systemctl daemon-reload and systemctl enable --now news-digest.service.

## Runtime behavior

The service starts `python bot.py` from the repository root. That process runs Telegram polling and the project scheduler concurrently. It must remain active; a missing token or invalid administrator ID configuration is a startup/configuration problem to resolve from logs.

- Status: systemctl status news-digest.service
- Logs: journalctl -u news-digest.service -f
- Restart: systemctl restart news-digest.service

For updates, back up SQLite, pull the intended revision, reinstall dependencies from requirements.txt in the same virtual environment and restart the service.

## Acceptance checks before enabling publishing

- The service remains active without restart loops.
- Telegram responds to /news help and /news projects.
- A configured administrator can create a project; a non-admin is denied.
- Project ownership checks prevent cross-user access.
- A test schedule becomes due and executes; scheduler errors are logged and polling continues.
- A test project collects, processes and queues articles.
- A private test channel receives a photo post with caption or a text post; retries do not duplicate successful target deliveries.
- Only after these checks, set TELEGRAM_PUBLISHING_ENABLED=true.

The KontentFabrik adapter is not used by this standalone runtime. No KontentFabrik, ZenDigest or other server service is modified by this deployment recipe.
