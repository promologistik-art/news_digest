"""PixiePandora container entry point: run the standalone Telegram bot."""

from __future__ import annotations

import sys

from news_digest.cli import main as cli_main


if __name__ == "__main__":
    # The persistent runtime combines Telegram polling with the project scheduler.
    if len(sys.argv) == 1:
        sys.argv.append("--bot")
    cli_main()
