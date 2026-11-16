"""Transactional per-project publication queue backed by SQLite."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass(frozen=True, slots=True)
class QueueItem:
    id: int
    project_id: int
    article_id: int
    canonical_url: str
    title: str
    payload: dict[str, Any]
    attempts: int
    target_ids: tuple[str, ...]


class PublicationQueue:
    """Enqueue approved drafts and lease due work to a single publisher."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    async def enqueue(
        self,
        *,
        project_id: int,
        article_id: int,
        scheduled_for: str | None = None,
    ) -> bool:
        """Add an article only when this project has an approved editorial draft."""
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                INSERT INTO publication_queue (project_id, article_id, scheduled_for)
                SELECT pa.project_id, pa.article_id, ?
                FROM project_articles AS pa
                WHERE pa.project_id = ? AND pa.article_id = ?
                  AND pa.editorial_status = 'ready'
                  AND pa.editorial_payload IS NOT NULL
                ON CONFLICT(project_id, article_id) DO NOTHING
                """,
                (scheduled_for, project_id, article_id),
            )
            await connection.commit()
            return cursor.rowcount == 1

    async def claim_next(self, *, now: str) -> QueueItem | None:
        """Atomically lease the earliest due item, preventing concurrent double claims."""
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                """
                SELECT q.id, q.project_id, q.article_id, q.attempts,
                       a.canonical_url, a.title, pa.editorial_payload
                FROM publication_queue AS q
                JOIN articles AS a ON a.id = q.article_id
                JOIN project_articles AS pa
                  ON pa.project_id = q.project_id AND pa.article_id = q.article_id
                WHERE q.status = 'pending'
                  AND (q.scheduled_for IS NULL OR q.scheduled_for <= ?)
                  AND pa.editorial_status = 'ready'
                ORDER BY COALESCE(q.scheduled_for, q.created_at), q.id
                LIMIT 1
                """,
                (now,),
            )
            row = await cursor.fetchone()
            if row is None:
                await connection.commit()
                return None
            await connection.execute(
                """
                UPDATE publication_queue
                SET status = 'processing', attempts = attempts + 1, last_error = NULL
                WHERE id = ? AND status = 'pending'
                """,
                (row[0],),
            )
            targets_cursor = await connection.execute(
                """
                SELECT target_id FROM targets
                WHERE project_id = ? AND enabled = 1
                ORDER BY id
                """,
                (row[1],),
            )
            targets = tuple(item[0] for item in await targets_cursor.fetchall())
            await connection.commit()
        return QueueItem(
            id=row[0],
            project_id=row[1],
            article_id=row[2],
            attempts=row[3] + 1,
            canonical_url=row[4],
            title=row[5],
            payload=json.loads(row[6]),
            target_ids=targets,
        )

    async def mark_published(
        self,
        item: QueueItem,
        *,
        messages: dict[str, str],
        caption_length: int,
    ) -> None:
        """Record per-target delivery and close the queue item in one transaction."""
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute("BEGIN IMMEDIATE")
            cursor = await connection.execute(
                "SELECT status FROM publication_queue WHERE id = ?",
                (item.id,),
            )
            row = await cursor.fetchone()
            if row is None or row[0] != "processing":
                raise ValueError("Queue item is not currently leased for publication.")
            for target_id, message_id in messages.items():
                await connection.execute(
                    """
                    INSERT INTO publication_history (
                        project_id, article_id, target_id, telegram_message_id,
                        caption_length, status
                    ) VALUES (?, ?, ?, ?, ?, 'published')
                    """,
                    (item.project_id, item.article_id, target_id, message_id, caption_length),
                )
            await connection.execute(
                "UPDATE publication_queue SET status = 'published' WHERE id = ?",
                (item.id,),
            )
            await connection.commit()

    async def mark_failed(
        self,
        item: QueueItem,
        *,
        error: str,
        retry_at: str | None,
        max_attempts: int = 5,
    ) -> str:
        """Retry transient failures or mark the item terminally failed."""
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one.")
        status = "pending" if retry_at is not None and item.attempts < max_attempts else "failed"
        async with aiosqlite.connect(self.database_path) as connection:
            cursor = await connection.execute(
                """
                UPDATE publication_queue
                SET status = ?, scheduled_for = ?, last_error = ?
                WHERE id = ? AND status = 'processing'
                """,
                (status, retry_at if status == "pending" else None, error[:2000], item.id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Queue item is not currently leased for publication.")
            await connection.commit()
        return status
