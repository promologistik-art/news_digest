"""Transactional per-project queue with target-level delivery idempotency."""

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
    image_url: str | None
    payload: dict[str, Any]
    attempts: int
    target_ids: tuple[str, ...]


class PublicationQueue:
    """Lease queue items and persist each target success before attempting the next."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)

    async def enqueue(
        self, *, project_id: int, article_id: int, scheduled_for: str | None = None
    ) -> bool:
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                INSERT INTO publication_queue (project_id, article_id, scheduled_for)
                SELECT pa.project_id, pa.article_id, ?
                FROM project_articles pa
                WHERE pa.project_id = ? AND pa.article_id = ?
                  AND pa.editorial_status = 'ready' AND pa.editorial_payload IS NOT NULL
                ON CONFLICT(project_id, article_id) DO NOTHING
                """,
                (scheduled_for, project_id, article_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def claim_next(self, *, now: str, lease_minutes: int = 10) -> QueueItem | None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT q.id, q.project_id, q.article_id, q.attempts,
                       a.canonical_url, a.title, a.image_url, pa.editorial_payload
                FROM publication_queue q
                JOIN articles a ON a.id = q.article_id
                JOIN project_articles pa
                  ON pa.project_id = q.project_id AND pa.article_id = q.article_id
                WHERE q.status IN ('pending', 'processing')
                  AND (q.scheduled_for IS NULL OR q.scheduled_for <= ?)
                  AND (q.status = 'pending' OR q.lease_until IS NULL OR q.lease_until <= ?)
                  AND pa.editorial_status = 'ready'
                  AND EXISTS (
                    SELECT 1 FROM targets t
                    WHERE t.project_id = q.project_id AND t.enabled = 1
                  )
                ORDER BY COALESCE(q.scheduled_for, q.created_at), q.id LIMIT 1
                """,
                (now, now),
            )
            row = await cursor.fetchone()
            if row is None:
                await db.commit()
                return None
            await db.execute(
                """
                UPDATE publication_queue
                SET status = 'processing', attempts = attempts + 1,
                    lease_until = datetime(?, ?), last_error = NULL
                WHERE id = ?
                """,
                (now, f"+{lease_minutes} minutes", row[0]),
            )
            target_cursor = await db.execute(
                """
                SELECT t.target_id FROM targets t
                WHERE t.project_id = ? AND t.enabled = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM publication_deliveries d
                    WHERE d.queue_id = ? AND d.target_id = t.target_id
                      AND d.status = 'published'
                  )
                ORDER BY t.id
                """,
                (row[1], row[0]),
            )
            target_ids = tuple(item[0] for item in await target_cursor.fetchall())
            await db.commit()
        return QueueItem(
            id=row[0], project_id=row[1], article_id=row[2],
            attempts=row[3] + 1, canonical_url=row[4], title=row[5],
            image_url=row[6], payload=json.loads(row[7]), target_ids=target_ids,
        )

    async def mark_target_published(
        self, item: QueueItem, *, target_id: str, message_id: str, caption_length: int
    ) -> None:
        if target_id not in item.target_ids:
            raise ValueError("Target is not pending for this queue lease.")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO publication_deliveries
                    (queue_id, project_id, article_id, target_id, status,
                     telegram_message_id, caption_length, published_at)
                VALUES (?, ?, ?, ?, 'published', ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(queue_id, target_id) DO UPDATE SET
                    status='published', telegram_message_id=excluded.telegram_message_id,
                    caption_length=excluded.caption_length, error=NULL,
                    published_at=CURRENT_TIMESTAMP
                """,
                (item.id, item.project_id, item.article_id, target_id, message_id, caption_length),
            )
            await db.execute(
                """
                INSERT INTO publication_history (
                    project_id, article_id, target_id, telegram_message_id,
                    caption_length, status
                ) VALUES (?, ?, ?, ?, ?, 'published')
                """,
                (item.project_id, item.article_id, target_id, message_id, caption_length),
            )
            await db.commit()

    async def finish_if_complete(self, item: QueueItem) -> bool:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            cursor = await db.execute(
                """
                SELECT COUNT(*) FROM targets t
                WHERE t.project_id = ? AND t.enabled = 1
                  AND NOT EXISTS (
                    SELECT 1 FROM publication_deliveries d
                    WHERE d.queue_id = ? AND d.target_id = t.target_id
                      AND d.status = 'published'
                  )
                """,
                (item.project_id, item.id),
            )
            remaining = (await cursor.fetchone())[0]
            if remaining == 0:
                await db.execute(
                    "UPDATE publication_queue SET status='published', lease_until=NULL "
                    "WHERE id=? AND status='processing'",
                    (item.id,),
                )
            await db.commit()
            return remaining == 0

    async def mark_failed(
        self, item: QueueItem, *, target_id: str, error: str,
        retry_at: str | None, max_attempts: int = 5,
    ) -> str:
        status = "pending" if retry_at is not None and item.attempts < max_attempts else "failed"
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute(
                """
                INSERT INTO publication_deliveries
                    (queue_id, project_id, article_id, target_id, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(queue_id, target_id) DO UPDATE SET
                    status=excluded.status, error=excluded.error
                WHERE publication_deliveries.status != 'published'
                """,
                (item.id, item.project_id, item.article_id, target_id, status, error[:2000]),
            )
            await db.execute(
                """
                INSERT INTO publication_history
                    (project_id, article_id, target_id, status, error)
                VALUES (?, ?, ?, 'failed', ?)
                """,
                (item.project_id, item.article_id, target_id, error[:2000]),
            )
            await db.execute(
                """
                UPDATE publication_queue SET status=?, scheduled_for=?, lease_until=NULL,
                    last_error=? WHERE id=? AND status='processing'
                """,
                (status, retry_at if status == "pending" else None, error[:2000], item.id),
            )
            await db.commit()
        return status
