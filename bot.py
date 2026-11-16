"""PixiePandora entry point.

PixiePandora starts Python projects with `python bot.py`.
Run the standalone Telegram bot together with the project scheduler.
"""

from __future__ import annotations

import sys

from news_digest.cli import main as cli_main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("--bot")
    cli_main()
