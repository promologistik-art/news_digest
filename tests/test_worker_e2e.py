from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from news_digest.ai.routerai import ChatResult, TokenUsage
from news_digest.collection.normalization import normalize_article
from news_digest.config import Settings
from news_digest.storage.database import Database
from news_digest.storage.project_repository import ProjectRepository
from news_digest.storage.publication_queue import PublicationQueue
from news_digest.storage.repositories import ArticleRepository
from news_digest import worker


class FakeCollector:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def collect_shared(self, *_: object, **__: object) -> int:
        return 0

    async def collect_project(self, project_id, database, _settings) -> int:
        article = normalize_article(
            url="https://example.com/culture/story",
            title="Museum opens a new exhibition",
            description="The museum opened a new exhibition today.",
            content=(
                "The museum opened a new exhibition today. "
                "The exhibition presents works by contemporary artists."
            ),
            published_at=datetime.now(UTC).isoformat(),
            image_url="https://example.com/culture/story.jpg",
        )
        repository = ArticleRepository(database.path)
        stored = await repository.save_articles([article])
        await repository.attach_to_project(
            project_id=project_id,
            article_id=stored[0].article_id,
        )
        return int(stored[0].inserted)


class FakeAI:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def chat(self, *, operation: str, **_kwargs) -> ChatResult:
        if operation == "editorial_assessment":
            content = {
                "relevant": True,
                "topic": "Culture",
                "geography": "Russia",
                "relevance_score": 95,
                "significance_score": 90,
                "novelty_score": 85,
                "confidence": 95,
                "article_date": None,
                "event_date": None,
                "factual_points": [
                    "The museum opened a new exhibition today."
                ],
                "uncertainties": [],
                "rejection_reason": None,
            }
        else:
            content = {
                "headline": "Museum opens a new exhibition",
                "caption": (
                    "The museum opened a new exhibition today. "
                    "It presents works by contemporary artists."
                ),
                "source_url": "https://example.com/culture/story",
                "factual_points_used": [
                    "The museum opened a new exhibition today."
                ],
                "caveat": None,
            }
        return ChatResult(
            content=json.dumps(content),
            model="deepseek/deepseek-v4.1-flash",
            provider="DeepSeek",
            request_id=f"request-{operation}",
            usage=TokenUsage(prompt_tokens=120, completion_tokens=60, total_tokens=180),
            raw={},
        )


class FakePublisher:
    def __init__(self, _token: str, queue: PublicationQueue) -> None:
        self.queue = queue

    async def publish(self, item) -> tuple[int, int]:
        for target_id in item.target_ids:
            await self.queue.mark_target_published(
                item,
                target_id=target_id,
                message_id=f"fake-{target_id}",
                caption_length=120,
            )
        await self.queue.finish_if_complete(item)
        return len(item.target_ids), 0


@pytest.mark.asyncio
async def test_end_to_end_collection_editorial_queue_and_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "e2e.sqlite3"
    await Database(database_path).initialize()
    projects = ProjectRepository(database_path)
    project_id = await projects.create_project(
        external_user_id="owner",
        slug="culture",
        name="Culture",
    )
    await projects.set_project_status(project_id=project_id, status="active")
    await projects.save_rules(
        project_id=project_id,
        rules={
            "topics": ["Culture"],
            "geographies": ["Russia"],
            "max_age_hours": 72,
        },
    )
    await projects.add_target(
        project_id=project_id,
        target_id="@culture_channel",
        enabled=True,
    )

    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{database_path}",
        routerai_api_key="test-key",
        telegram_bot_token="test-token",
        telegram_publishing_enabled=True,
    )
    monkeypatch.setattr(worker, "RSSCollector", FakeCollector)
    monkeypatch.setattr(worker, "RouterAIClient", lambda _settings: FakeAI())
    monkeypatch.setattr(worker, "TelegramPublisher", FakePublisher)

    totals = await worker.run_once(settings)

    assert totals == {
        "collected": 1,
        "assessed": 1,
        "queued": 1,
        "published": 1,
        "failed": 0,
    }
    async with aiosqlite.connect(database_path) as db:
        editorial = await db.execute_fetchall(
            "SELECT editorial_status FROM project_articles WHERE project_id=?",
            (project_id,),
        )
        queue = await db.execute_fetchall(
            "SELECT status, attempts FROM publication_queue WHERE project_id=?",
            (project_id,),
        )
        deliveries = await db.execute_fetchall(
            "SELECT target_id, status FROM publication_deliveries"
        )
        usage = await db.execute_fetchall(
            "SELECT operation, input_tokens, output_tokens FROM ai_usage "
            "WHERE project_id=? ORDER BY id",
            (project_id,),
        )

    assert editorial == [("ready",)]
    assert queue == [("published", 1)]
    assert deliveries == [("@culture_channel", "published")]
    assert usage == [
        ("editorial_assessment", 120, 60),
        ("editorial_draft", 120, 60),
    ]
