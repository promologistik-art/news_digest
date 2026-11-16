"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Sequence

from news_digest.ai.routerai import RouterAIClient, RouterAIError
from news_digest.config import Settings
from news_digest.scheduling.service import ProjectScheduler
from news_digest.storage.database import Database
from news_digest.telegram_admin import build_application
from news_digest.worker import run_once


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-digest")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument(
        "--test-ai",
        action="store_true",
        help="Send a minimal test prompt to the configured AI model.",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--scheduler", action="store_true")
    parser.add_argument(
        "--service",
        action="store_true",
        help="Run the project scheduler and standalone Telegram administration bot.",
    )
    return parser


async def _run_service(settings: Settings) -> int:
    database = Database(settings.database_path)
    await database.initialize()
    application = build_application(settings)
    await application.initialize()
    await application.start()
    if application.updater is None:
        raise RuntimeError("Telegram polling updater is unavailable.")
    await application.updater.start_polling()
    logger = logging.getLogger(__name__)
    logger.info(
        "news_digest service started; Telegram admins configured: %s",
        len(settings.telegram_admin_id_set),
    )
    try:
        await ProjectScheduler(settings).run_forever()
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
    return 0


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.check_config:
        key_configured = bool(settings.routerai_api_key.get_secret_value())
        print(
            f"Configuration OK; provider={settings.ai_provider}; "
            f"model={settings.ai_model}; timezone={settings.timezone}; "
            f"RouterAI key={'configured' if key_configured else 'missing'}; "
            f"Telegram token={'configured' if settings.telegram_bot_token.get_secret_value() else 'missing'}; "
            f"Telegram admins={len(settings.telegram_admin_id_set)}"
        )
        return 0

    if args.init_db:
        database = Database(settings.database_path)
        await database.initialize()
        print(f"Database initialized: {settings.database_path}")
        return 0

    if args.test_ai:
        if not settings.routerai_api_key.get_secret_value():
            print("ROUTERAI_API_KEY is not configured. Add it to .env; do not commit the file.")
            return 2
        client = RouterAIClient(settings)
        try:
            result = await client.chat(
                messages=[{"role": "user", "content": "Ответь одним словом: готово"}],
                max_tokens=32,
                operation="connection_test",
            )
        except RouterAIError as exc:
            print(f"RouterAI test failed: {exc}")
            return 1
        print(f"RouterAI OK; model={result.model}; answer={result.content!r}")
        if result.usage:
            print(
                "Tokens: "
                f"input={result.usage.prompt_tokens}, "
                f"output={result.usage.completion_tokens}, "
                f"total={result.usage.total_tokens}"
            )
        if result.provider:
            print(f"Provider: {result.provider}")
        return 0

    if args.service:
        return await _run_service(settings)

    if args.scheduler:
        await ProjectScheduler(settings).run_forever()
        return 0

    if args.once:
        totals = await run_once(settings)
        print(
            "Worker run complete: "
            + ", ".join(f"{key}={value}" for key, value in totals.items())
        )
        if not settings.telegram_publishing_enabled:
            print("Publishing is disabled; approved drafts remain safely queued.")
        return 0

    print(
        "Use --service (production), --check-config, --init-db, "
        "--test-ai, --once or --scheduler."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
