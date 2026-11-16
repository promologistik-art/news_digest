"""SQLite database bootstrap and initial multi-project schema."""

# ruff: noqa: I001  # Keep the conventional stdlib/third-party import split explicit.

from __future__ import annotations

from pathlib import Path

import aiosqlite


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_user_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    language TEXT NOT NULL DEFAULT 'ru',
    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_topics (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (project_id, topic_id)
);

CREATE TABLE IF NOT EXISTS geographies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_geographies (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    geography_id INTEGER NOT NULL REFERENCES geographies(id) ON DELETE CASCADE,
    weight REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (project_id, geography_id)
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL DEFAULT 'rss',
    name TEXT,
    reliability_score REAL NOT NULL DEFAULT 0.5,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_sources (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    source_mode TEXT NOT NULL DEFAULT 'shared',
    enabled INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (project_id, source_id)
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT,
    content TEXT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    author TEXT,
    language TEXT,
    published_at TEXT,
    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    content_hash TEXT NOT NULL,
    image_url TEXT,
    raw_metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at);
CREATE INDEX IF NOT EXISTS idx_articles_content_hash ON articles(content_hash);

CREATE TABLE IF NOT EXISTS project_articles (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    relevance_score REAL,
    significance_score REAL,
    editorial_status TEXT NOT NULL DEFAULT 'new',
    editorial_payload TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, article_id)
);

CREATE TABLE IF NOT EXISTS project_rules (
    project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    rules_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform TEXT NOT NULL DEFAULT 'telegram',
    target_id TEXT NOT NULL,
    title TEXT,
    enabled INTEGER NOT NULL DEFAULT 0,
    UNIQUE(project_id, platform, target_id)
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    cron_expression TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Europe/Moscow',
    enabled INTEGER NOT NULL DEFAULT 0,
    next_run_at TEXT,
    last_run_at TEXT,
    last_error TEXT,
    lease_until TEXT
);

CREATE TABLE IF NOT EXISTS publication_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    scheduled_for TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    lease_until TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, article_id)
);

CREATE TABLE IF NOT EXISTS publication_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL,
    telegram_message_id TEXT,
    published_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    caption_length INTEGER,
    status TEXT NOT NULL,
    error TEXT
);

CREATE TABLE IF NOT EXISTS publication_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    queue_id INTEGER NOT NULL REFERENCES publication_queue(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    target_id TEXT NOT NULL,
    status TEXT NOT NULL,
    telegram_message_id TEXT,
    caption_length INTEGER,
    error TEXT,
    published_at TEXT,
    UNIQUE(queue_id, target_id)
);

CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    operation TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    cost_amount REAL,
    cost_currency TEXT,
    request_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as connection:
            await connection.executescript(SCHEMA)
            queue_columns = await connection.execute_fetchall("PRAGMA table_info(publication_queue)")
            if "lease_until" not in {column[1] for column in queue_columns}:
                await connection.execute("ALTER TABLE publication_queue ADD COLUMN lease_until TEXT")
            schedule_columns = await connection.execute_fetchall("PRAGMA table_info(schedules)")
            existing_schedule_columns = {column[1] for column in schedule_columns}
            for column_name in ("next_run_at", "last_run_at", "last_error", "lease_until"):
                if column_name not in existing_schedule_columns:
                    await connection.execute(
                        f"ALTER TABLE schedules ADD COLUMN {column_name} TEXT"
                    )
            columns = await connection.execute_fetchall("PRAGMA table_info(ai_usage)")
            if "total_tokens" not in {column[1] for column in columns}:
                await connection.execute("ALTER TABLE ai_usage ADD COLUMN total_tokens INTEGER")
            await connection.commit()
