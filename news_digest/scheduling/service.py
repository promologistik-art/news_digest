"""Timezone-aware cron scheduler for independent projects."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from news_digest.config import Settings
from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository
from news_digest.worker import run_once

logger = logging.getLogger(__name__)


class ProjectScheduler:
    def __init__(self, settings: Settings, *, poll_seconds: int = 20) -> None:
        self.settings = settings
        self.poll_seconds = poll_seconds
        self.projects = ProjectRepository(settings.database_path)

    async def run_forever(self) -> None:
        await Database(self.settings.database_path).initialize()
        logger.info("Project scheduler started (poll=%ss)", self.poll_seconds)
        while True:
            try:
                await self.run_due()
            except Exception:
                logger.exception("Scheduler polling cycle failed; will retry")
            await asyncio.sleep(self.poll_seconds)

    async def run_due(self) -> int:
        due = await self.projects.claim_due_schedules(now_utc=datetime.now(UTC))
        completed = 0
        for schedule_id, project_id, cron_expression, timezone in due:
            error = None
            try:
                await run_once(self.settings, project_id=project_id)
                completed += 1
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                logger.exception(
                    "Scheduled project run failed: project=%s schedule=%s",
                    project_id, schedule_id,
                )
            finally:
                await self.projects.finish_schedule(
                    schedule_id=schedule_id, cron_expression=cron_expression,
                    timezone=timezone, finished_at=datetime.now(UTC), error=error,
                )
        return completed
