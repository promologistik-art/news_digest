from __future__ import annotations

import json

import aiosqlite
import pytest

from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository
from news_digest.storage.publication_queue import PublicationQueue


@pytest.mark.asyncio
async def test_projects_are_isolated_by_owner_and_allow_multiple_projects(tmp_path) -> None:
    path = tmp_path / "projects.sqlite3"
    await Database(path).initialize()
    projects = ProjectRepository(path)
    first = await projects.create_project(
        external_user_id="user-a", slug="culture-a", name="Culture"
    )
    second = await projects.create_project(
        external_user_id="user-a", slug="tech-a", name="Technology"
    )
    await projects.create_project(
        external_user_id="user-b", slug="culture-b", name="Culture"
    )

    owned = await projects.list_projects(external_user_id="user-a")
    assert [item["id"] for item in owned] == [first, second]
    assert [item["slug"] for item in owned] == ["culture-a", "tech-a"]


async def _prepare_ready_item(path, targets=("@channel_a", "@channel_b")):
    await Database(path).initialize()
    projects = ProjectRepository(path)
    project_id = await projects.create_project(
        external_user_id="owner", slug="culture", name="Culture"
    )
    for target in targets:
        await projects.add_target(project_id=project_id, target_id=target, enabled=True)
    async with aiosqlite.connect(path) as db:
        await db.execute(
            "INSERT INTO articles (canonical_url, title, content_hash) VALUES (?, ?, ?)",
            ("https://example.com/story", "Story", "fingerprint"),
        )
        await db.execute(
            """
            INSERT INTO project_articles (
                project_id, article_id, editorial_status, editorial_payload
            ) VALUES (?, 1, 'ready', ?)
            """,
            (project_id, json.dumps({"draft": {"headline": "Headline", "caption": "Text"}})),
        )
        await db.commit()
    queue = PublicationQueue(path)
    assert await queue.enqueue(project_id=project_id, article_id=1)
    return queue, project_id


@pytest.mark.asyncio
async def test_partial_delivery_retry_skips_already_published_target(tmp_path) -> None:
    path = tmp_path / "partial.sqlite3"
    queue, _ = await _prepare_ready_item(path)
    item = await queue.claim_next(now="2026-11-16 10:00:00")
    assert item is not None
    assert item.target_ids == ("@channel_a", "@channel_b")

    await queue.mark_target_published(
        item, target_id="@channel_a", message_id="message-1", caption_length=20
    )
    assert await queue.mark_failed(
        item, target_id="@channel_b", error="temporary network error",
        retry_at="2026-11-16 10:05:00", max_attempts=5,
    ) == "pending"
    assert await queue.finish_if_complete(item) is False

    retry = await queue.claim_next(now="2026-11-16 10:06:00")
    assert retry is not None
    assert retry.target_ids == ("@channel_b",)
    await queue.mark_target_published(
        retry, target_id="@channel_b", message_id="message-2", caption_length=20
    )
    assert await queue.finish_if_complete(retry) is True

    async with aiosqlite.connect(path) as db:
        statuses = await db.execute_fetchall(
            "SELECT target_id, status FROM publication_deliveries ORDER BY target_id"
        )
        history = await db.execute_fetchall(
            "SELECT target_id, telegram_message_id FROM publication_history "
            "WHERE status='published' ORDER BY target_id"
        )
        queue_status = await db.execute_fetchall(
            "SELECT status FROM publication_queue"
        )
    assert statuses == [("@channel_a", "published"), ("@channel_b", "published")]
    assert history == [("@channel_a", "message-1"), ("@channel_b", "message-2")]
    assert queue_status == [("published",)]


@pytest.mark.asyncio
async def test_expired_lease_can_be_reclaimed_without_duplicate_delivery(tmp_path) -> None:
    path = tmp_path / "lease.sqlite3"
    queue, _ = await _prepare_ready_item(path, targets=("@channel_a",))
    first = await queue.claim_next(now="2026-11-16 10:00:00", lease_minutes=5)
    assert first is not None
    assert await queue.claim_next(now="2026-11-16 10:04:59") is None

    reclaimed = await queue.claim_next(now="2026-11-16 10:05:01")
    assert reclaimed is not None
    assert reclaimed.id == first.id
    assert reclaimed.target_ids == ("@channel_a",)



@pytest.mark.asyncio
async def test_permanently_failed_item_can_be_manually_retried(tmp_path) -> None:
    path = tmp_path / "manual-retry.sqlite3"
    queue, project_id = await _prepare_ready_item(path, targets=("@channel_a",))
    item = await queue.claim_next(now="2026-11-16 10:00:00")
    assert item is not None
    assert await queue.mark_failed(
        item,
        target_id="@channel_a",
        error="permanent failure after retry budget",
        retry_at=None,
        max_attempts=1,
    ) == "failed"

    assert await queue.retry_failed(queue_id=item.id) is True
    assert await queue.retry_failed(queue_id=item.id) is False
    retry = await queue.claim_next(now="2026-11-16 10:01:00")
    assert retry is not None
    assert retry.attempts == 1
    assert retry.target_ids == ("@channel_a",)

    queue_items = await queue.list_project_queue(project_id=project_id)
    assert queue_items[0]["status"] == "processing"
    deliveries = await queue.list_deliveries(queue_id=item.id)
    assert deliveries[0]["status"] == "failed"
