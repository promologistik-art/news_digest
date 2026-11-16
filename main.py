"""PixiePandora container entry point: run the persistent project scheduler."""

from __future__ import annotations

import sys

from news_digest.cli import main as cli_main


if __name__ == "__main__":
    # PixiePandora starts the project with `python main.py`.
    # Default to the long-running scheduler; explicit CLI flags remain supported.
    if len(sys.argv) == 1:
        sys.argv.append("--scheduler")
    cli_main()
