"""Command-line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from news_digest.config import Settings
from news_digest.storage.database import Database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="news-digest")
    parser.add_argument("--check-config", action="store_true")
    parser.add_argument("--init-db", action="store_true")
    parser.add_argument("--once", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = Settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.check_config:
        print(
            f"Configuration OK; provider={settings.ai_provider}; "
            f"model={settings.ai_model}; timezone={settings.timezone}"
        )
        return 0

    if args.init_db:
        database = Database(settings.database_path)
        await database.initialize()
        print(f"Database initialized: {settings.database_path}")
        return 0

    if args.once:
        if not settings.telegram_publishing_enabled:
            print("Publishing is disabled. Configure and explicitly enable it before publishing.")
        else:
            print("Worker pipeline is not wired yet; no publication was attempted.")
        return 0

    print("Use --check-config, --init-db or --once.")
    return 0


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
