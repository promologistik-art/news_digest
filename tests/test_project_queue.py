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


@pytest.mark.asyncio
async def test_queue_only_claims_ready_project_article_and_records_publication(tmp_path) -> None:
    path = tmp_path / "queue.sqlite3"
    await Database(path).initialize()
    projects = ProjectRepository(path)
    project_id = await projects.create_project(
        external_user_id="owner", slug="culture", name="Culture"
    )
    await projects.add_target(
        project_id=project_id, target_id="@culture_channel", enabled=True
    )

    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            "INSERT INTO articles (canonical_url, title, content_hash) "
            "VALUES (?, ?, ?)",
            ("https://example.com/story", "Story", "hash"),
        )
        await connection.execute(
            """
            INSERT INTO project_articles (
                project_id, article_id, editorial_status, editorial_payload
            ) VALUES (?, 1, 'ready', ?)
            """,
            (
                project_id,
                json.dumps(
                    {
                        "draft": {
                            "headline": "Headline",
                            "caption": "Caption",
                            "source_url": "https://example.com/story",
                        }
                    }
                ),
            ),
        )
        await connection.commit()

    queue = PublicationQueue(path)
    assert await queue.enqueue(project_id=project_id, article_id=1) is True
    assert await queue.enqueue(project_id=project_id, article_id=1) is False
    item = await queue.claim_next(now="2099-01-01T00:00:00")
    assert item is not None
    assert item.target_ids == ("@culture_channel",)
    assert item.payload["draft"]["headline"] == "Headline"
    assert await queue.claim_next(now="2099-01-01T00:00:00") is None

    await queue.mark_published(
        item,
        messages={"@culture_channel": "telegram-message-123"},
        caption_length=7,
    )
    async with aiosqlite.connect(path) as connection:
        status = await connection.execute_fetchall(
            "SELECT status FROM publication_queue WHERE id = ?", (item.id,)
        )
        history = await connection.execute_fetchall(
            "SELECT target_id, telegram_message_id, status FROM publication_history"
        )
    assert status == [("published",)]
    assert history == [("@culture_channel", "telegram-message-123", "published")]


@pytest.mark.asyncio
async def test_queue_retries_then_fails_after_attempt_limit(tmp_path) -> None:
    path = tmp_path / "retry.sqlite3"
    await Database(path).initialize()
    projects = ProjectRepository(path)
    project_id = await projects.create_project(
        external_user_id="owner", slug="daily", name="Daily"
    )
    async with aiosqlite.connect(path) as connection:
        await connection.execute(
            "INSERT INTO articles (canonical_url, title, content_hash) "
            "VALUES (?, ?, ?)",
            ("https://example.com/a", "A", "hash"),
        )
        await connection.execute(
            """
            INSERT INTO project_articles (
                project_id, article_id, editorial_status, editorial_payload
            ) VALUES (?, 1, 'ready', '{}')
            """,
            (project_id,),
        )
        await connection.commit()
    queue = PublicationQueue(path)
    await queue.enqueue(project_id=project_id, article_id=1)
    item = await queue.claim_next(now="2099-01-01T00:00:00")
    assert item is not None
    assert await queue.mark_failed(
        item, error="temporary", retry_at="2099-01-02T00:00:00", max_attempts=2
    ) == "pending"
    item = await queue.claim_next(now="2099-01-03T00:00:00")
    assert item is not None
    assert await queue.mark_failed(
        item, error="permanent", retry_at="2099-01-04T00:00:00", max_attempts=2
    ) == "failed"
