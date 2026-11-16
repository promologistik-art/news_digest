from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from news_digest.storage.database import SCHEMA_VERSION, Database


@pytest.mark.asyncio
async def test_existing_sqlite_database_is_upgraded_and_versioned(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            """
            CREATE TABLE publication_queue (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                article_id INTEGER,
                status TEXT,
                scheduled_for TEXT,
                attempts INTEGER,
                last_error TEXT,
                created_at TEXT
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE schedules (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                cron_expression TEXT,
                timezone TEXT,
                enabled INTEGER
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE ai_usage (
                id INTEGER PRIMARY KEY,
                project_id INTEGER,
                provider TEXT,
                model TEXT,
                operation TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cost_amount REAL,
                cost_currency TEXT,
                request_id TEXT,
                created_at TEXT
            )
            """
        )
        await db.commit()

    await Database(database_path).initialize()

    async with aiosqlite.connect(database_path) as db:
        queue_columns = {
            row[1] for row in await db.execute_fetchall("PRAGMA table_info(publication_queue)")
        }
        schedule_columns = {
            row[1] for row in await db.execute_fetchall("PRAGMA table_info(schedules)")
        }
        usage_columns = {
            row[1] for row in await db.execute_fetchall("PRAGMA table_info(ai_usage)")
        }
        version = await db.execute_fetchall("PRAGMA user_version")

    assert "lease_until" in queue_columns
    assert {"next_run_at", "last_run_at", "last_error", "lease_until"} <= schedule_columns
    assert {
        "total_tokens",
        "cached_input_tokens",
        "cost_estimated",
    } <= usage_columns
    assert version == [(SCHEMA_VERSION,)]
