"""Tests for shared article storage and project-level isolation."""

from pathlib import Path

import pytest

from news_digest.collection.normalization import normalize_article
from news_digest.storage.database import Database
from news_digest.storage.repositories import ArticleRepository


@pytest.mark.asyncio
async def test_articles_are_shared_and_project_links_are_isolated(tmp_path: Path) -> None:
    database_path = tmp_path / "news.sqlite3"
    await Database(database_path).initialize()
    repository = ArticleRepository(database_path)

    source_id = await repository.register_source(
        url="https://example.com/feed.xml",
        name="Example",
    )
    article = normalize_article(
        url="https://example.com/story",
        title="Important news",
        description="A meaningful summary",
    )
    first = await repository.save_articles([article], source_id=source_id)
    second = await repository.save_articles([article], source_id=source_id)

    assert first[0].inserted is True
    assert second[0].inserted is False
    assert first[0].article_id == second[0].article_id

    await repository.attach_to_project(
        project_id=1,
        article_id=first[0].article_id,
        relevance_score=0.9,
    )
    await repository.attach_to_project(
        project_id=2,
        article_id=first[0].article_id,
        relevance_score=0.4,
    )

    import aiosqlite

    async with aiosqlite.connect(database_path) as db:
        rows = await db.execute_fetchall(
            "SELECT project_id, relevance_score FROM project_articles ORDER BY project_id"
        )
    assert rows == [(1, 0.9), (2, 0.4)]
