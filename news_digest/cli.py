"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging

from news_digest.ai.routerai import RouterAIClient, RouterAIError
from news_digest.config import Settings
from news_digest.scheduling.service import ProjectScheduler
from news_digest.storage.database import Database
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
    parser.add_argument("--bot", action="store_true", help="Run the standalone Telegram bot and scheduler.")
    return parser


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
            f"Telegram admins={len(settings.admin_telegram_ids_set)}"
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

    print("Use --bot, --check-config, --init-db, --test-ai, --once or --scheduler.")
    return 0


def main() -> None:
    args = build_parser().parse_args()
    if args.bot:
        settings = Settings()
        logging.basicConfig(
            level=settings.log_level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        from news_digest.telegram_bot import run_bot

        run_bot(settings)
        return
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
