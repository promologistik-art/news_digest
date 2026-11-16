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
        normalized_rules = _validate_rules(rules)
        encoded = json.dumps(normalized_rules, ensure_ascii=False)
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
        _validate_feed_url(clean_url)
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


    async def add_target(
        self, *, project_id: int, target_id: str, title: str | None = None,
        platform: str = "telegram", enabled: bool = False,
    ) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO targets (project_id, platform, target_id, title, enabled)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, platform, target_id) DO UPDATE SET
                    title=excluded.title, enabled=excluded.enabled
                """, (project_id, platform, target_id, title, int(enabled)),
            )
            cursor = await db.execute(
                """
                SELECT id FROM targets
                WHERE project_id=? AND platform=? AND target_id=?
                """, (project_id, platform, target_id),
            )
            row = await cursor.fetchone()
            await db.commit()
            return int(row[0])

    async def list_targets(self, *, project_id: int) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT id, platform, target_id, title, enabled
                FROM targets WHERE project_id=? ORDER BY id
                """, (project_id,),
            )
            rows = await cursor.fetchall()
        return [
            {"id": row[0], "platform": row[1], "target_id": row[2],
             "title": row[3], "enabled": bool(row[4])}
            for row in rows
        ]

    async def set_target_enabled(
        self, *, project_id: int, target_id: str, enabled: bool,
        platform: str = "telegram",
    ) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                UPDATE targets SET enabled=?
                WHERE project_id=? AND platform=? AND target_id=?
                """, (int(enabled), project_id, platform, target_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Target is not configured for this project.")
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



def _validate_rules(rules: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "topics",
        "geographies",
        "excluded_topics",
        "audience",
        "style_guide",
        "min_significance",
        "max_age_hours",
        "monthly_ai_budget_rub",
    }
    unknown = set(rules) - allowed
    if unknown:
        raise ValueError(f"Unsupported editorial rule keys: {', '.join(sorted(unknown))}.")
    normalized = dict(rules)
    for key in ("topics", "geographies", "excluded_topics"):
        values = normalized.get(key, [])
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError(f"{key} must be a list of non-empty strings.")
        normalized[key] = list(dict.fromkeys(value.strip() for value in values))
    for key, minimum, maximum in (
        ("min_significance", 0, 100),
        ("max_age_hours", 1, 8760),
    ):
        if key in normalized:
            value = normalized[key]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{key} must be an integer.")
            if not minimum <= value <= maximum:
                raise ValueError(f"{key} must be between {minimum} and {maximum}.")
    if "monthly_ai_budget_rub" in normalized:
        budget = normalized["monthly_ai_budget_rub"]
        if isinstance(budget, bool) or not isinstance(budget, (int, float)):
            raise ValueError("monthly_ai_budget_rub must be a non-negative number.")
        if budget < 0:
            raise ValueError("monthly_ai_budget_rub must be a non-negative number.")
        normalized["monthly_ai_budget_rub"] = float(budget)
    for key, maximum in (("audience", 1000), ("style_guide", 4000)):
        if key in normalized:
            value = normalized[key]
            if not isinstance(value, str) or len(value) > maximum:
                raise ValueError(f"{key} must be text no longer than {maximum} characters.")
    return normalized


def _validate_feed_url(value: str) -> None:
    from urllib.parse import urlsplit

    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Feed URL must be an absolute HTTP(S) URL.")
    if parts.username or parts.password:
        raise ValueError("Credentials are not allowed in feed URLs.")
