"""Multi-project ownership, settings and Telegram destination management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite


class ProjectRepository:
    """CRUD operations scoped to the owning application user."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    async def create_project(
        self,
        *,
        external_user_id: str,
        slug: str,
        name: str,
        language: str = "ru",
        timezone: str = "Europe/Moscow",
    ) -> int:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                "INSERT INTO users (external_user_id) VALUES (?) "
                "ON CONFLICT(external_user_id) DO NOTHING",
                (external_user_id,),
            )
            cursor = await connection.execute(
                "SELECT id FROM users WHERE external_user_id = ?",
                (external_user_id,),
            )
            owner = await cursor.fetchone()
            project = await connection.execute(
                """
                INSERT INTO projects (owner_user_id, slug, name, language, timezone)
                VALUES (?, ?, ?, ?, ?)
                """,
                (owner[0], slug, name, language, timezone),
            )
            await connection.commit()
            return int(project.lastrowid)

    async def list_projects(self, *, external_user_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                SELECT p.id, p.slug, p.name, p.status, p.language, p.timezone
                FROM projects AS p
                JOIN users AS u ON u.id = p.owner_user_id
                WHERE u.external_user_id = ?
                ORDER BY p.id
                """,
                (external_user_id,),
            )
            rows = await cursor.fetchall()
        return [
            {
                "id": row[0],
                "slug": row[1],
                "name": row[2],
                "status": row[3],
                "language": row[4],
                "timezone": row[5],
            }
            for row in rows
        ]

    async def save_rules(self, *, project_id: int, rules: dict[str, Any]) -> None:
        encoded = json.dumps(rules, ensure_ascii=False)
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO project_rules (project_id, rules_json)
                VALUES (?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    rules_json = excluded.rules_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (project_id, encoded),
            )
            await connection.commit()

    async def add_target(
        self,
        *,
        project_id: int,
        target_id: str,
        title: str | None = None,
        platform: str = "telegram",
        enabled: bool = False,
    ) -> int:
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO targets (project_id, platform, target_id, title, enabled)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id, platform, target_id) DO UPDATE SET
                    title = excluded.title, enabled = excluded.enabled
                """,
                (project_id, platform, target_id, title, int(enabled)),
            )
            cursor = await connection.execute(
                """
                SELECT id FROM targets
                WHERE project_id = ? AND platform = ? AND target_id = ?
                """,
                (project_id, platform, target_id),
            )
            row = await cursor.fetchone()
            await connection.commit()
            return int(row[0])

    async def set_schedule(
        self,
        *,
        project_id: int,
        cron_expression: str,
        timezone: str = "Europe/Moscow",
        enabled: bool = False,
    ) -> int:
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                INSERT INTO schedules (project_id, cron_expression, timezone, enabled)
                VALUES (?, ?, ?, ?)
                """,
                (project_id, cron_expression, timezone, int(enabled)),
            )
            await connection.commit()
            return int(cursor.lastrowid)
