"""Multi-project CRUD for settings, RSS sources, targets and schedules."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiosqlite
from croniter import croniter


class ProjectRepository:
    """CRUD operations scoped to the owning application user."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    async def create_project(
        self, *, external_user_id: str, slug: str, name: str,
        language: str = "ru", timezone: str = "Europe/Moscow",
    ) -> int:
        _validate_timezone(timezone)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                "INSERT INTO users (external_user_id) VALUES (?) "
                "ON CONFLICT(external_user_id) DO NOTHING", (external_user_id,),
            )
            cursor = await connection.execute(
                "SELECT id FROM users WHERE external_user_id = ?", (external_user_id,),
            )
            owner = await cursor.fetchone()
            project = await connection.execute(
                """
                INSERT INTO projects (owner_user_id, slug, name, language, timezone)
                VALUES (?, ?, ?, ?, ?)
                """, (owner[0], slug, name, language, timezone),
            )
            await connection.commit()
            return int(project.lastrowid)

    async def list_projects(self, *, external_user_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                SELECT p.id, p.slug, p.name, p.status, p.language, p.timezone
                FROM projects p JOIN users u ON u.id = p.owner_user_id
                WHERE u.external_user_id = ? ORDER BY p.id
                """, (external_user_id,),
            )
            rows = await cursor.fetchall()
        return [
            {"id": r[0], "slug": r[1], "name": r[2], "status": r[3],
             "language": r[4], "timezone": r[5]} for r in rows
        ]

    async def set_project_status(self, *, project_id: int, status: str) -> None:
        if status not in {"draft", "active", "paused", "archived"}:
            raise ValueError("Unsupported project status.")
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                "UPDATE projects SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (status, project_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Project does not exist.")
            await db.commit()

    async def save_rules(self, *, project_id: int, rules: dict[str, Any]) -> None:
        encoded = json.dumps(rules, ensure_ascii=False)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO project_rules (project_id, rules_json) VALUES (?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    rules_json=excluded.rules_json, updated_at=CURRENT_TIMESTAMP
                """, (project_id, encoded),
            )
            await connection.commit()

    async def get_rules(self, *, project_id: int) -> dict[str, Any]:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                "SELECT rules_json FROM project_rules WHERE project_id=?", (project_id,),
            )
            row = await cursor.fetchone()
        return json.loads(row[0]) if row else {}

    async def add_source(
        self, *, project_id: int, url: str, name: str | None = None,
        reliability_score: float = 0.5, source_mode: str = "project",
    ) -> int:
        if not 0 <= reliability_score <= 1:
            raise ValueError("reliability_score must be between 0 and 1.")
        if source_mode not in {"shared", "project"}:
            raise ValueError("source_mode must be 'shared' or 'project'.")
        clean_url = url.strip()
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO sources (url, name, reliability_score)
                VALUES (?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name=COALESCE(excluded.name, sources.name),
                    reliability_score=excluded.reliability_score, is_active=1
                """, (clean_url, name, reliability_score),
            )
            cursor = await db.execute("SELECT id FROM sources WHERE url=?", (clean_url,))
            source_id = int((await cursor.fetchone())[0])
            await db.execute(
                """
                INSERT INTO project_sources (project_id, source_id, source_mode, enabled)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(project_id, source_id) DO UPDATE SET
                    source_mode=excluded.source_mode, enabled=1
                """, (project_id, source_id, source_mode),
            )
            await db.commit()
            return source_id

    async def list_sources(self, *, project_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT s.id, s.name, s.url, s.source_type, s.reliability_score,
                       ps.source_mode, ps.enabled
                FROM sources s JOIN project_sources ps ON ps.source_id=s.id
                WHERE ps.project_id=? ORDER BY s.name, s.url
                """, (project_id,),
            )
            rows = await cursor.fetchall()
        return [
            {"id": r[0], "name": r[1], "url": r[2], "type": r[3],
             "reliability_score": r[4], "mode": r[5], "enabled": bool(r[6])}
            for r in rows
        ]

    async def set_source_enabled(
        self, *, project_id: int, source_id: int, enabled: bool
    ) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                "UPDATE project_sources SET enabled=? WHERE project_id=? AND source_id=?",
                (int(enabled), project_id, source_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Source is not assigned to this project.")
            await db.commit()

    async def set_schedule(
        self, *, project_id: int, cron_expression: str,
        timezone: str = "Europe/Moscow", enabled: bool = False,
    ) -> int:
        zone = _validate_timezone(timezone)
        now = datetime.now(zone)
        if not croniter.is_valid(cron_expression):
            raise ValueError("Invalid cron expression.")
        next_run = croniter(cron_expression, now).get_next(datetime).astimezone(UTC).replace(
            tzinfo=None
        ).isoformat(sep=" ", timespec="seconds")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                "UPDATE schedules SET enabled=0 WHERE project_id=?", (project_id,),
            )
            cursor = await db.execute(
                """
                INSERT INTO schedules (
                    project_id, cron_expression, timezone, enabled, next_run_at
                ) VALUES (?, ?, ?, ?, ?)
                """, (project_id, cron_expression, timezone, int(enabled), next_run),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def claim_due_schedules(self, *, now_utc: datetime, lease_minutes: int = 15):
        now_text = now_utc.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")
        until = (now_utc.replace(tzinfo=None) + timedelta(minutes=lease_minutes)).isoformat(
            sep=" ", timespec="seconds"
        )
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT id, project_id, cron_expression, timezone
                FROM schedules
                WHERE enabled=1 AND next_run_at<=?
                  AND (lease_until IS NULL OR lease_until<=?)
                ORDER BY next_run_at, id
                """, (now_text, now_text),
            )
            rows = await cursor.fetchall()
            for row in rows:
                await db.execute(
                    "UPDATE schedules SET lease_until=? WHERE id=?", (until, row[0]),
                )
            await db.commit()
        return rows

    async def finish_schedule(
        self, *, schedule_id: int, cron_expression: str, timezone: str,
        finished_at: datetime, error: str | None = None,
    ) -> None:
        zone = _validate_timezone(timezone)
        local_now = finished_at.astimezone(zone)
        next_run = croniter(cron_expression, local_now).get_next(datetime).astimezone(UTC).replace(
            tzinfo=None
        ).isoformat(sep=" ", timespec="seconds")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE schedules SET next_run_at=?, last_run_at=?, last_error=?,
                    lease_until=NULL WHERE id=?
                """,
                (next_run, finished_at.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),
                 error[:2000] if error else None, schedule_id),
            )
            await db.commit()


def _validate_timezone(value: str) -> ZoneInfo:
    try:
        return ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
