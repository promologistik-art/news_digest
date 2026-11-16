"""Tests for shared article storage and project-level isolation."""

from pathlib import Path

import aiosqlite
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

    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "INSERT INTO projects (slug, name) VALUES ('project-one', 'Project One')"
        )
        await db.execute(
            "INSERT INTO projects (slug, name) VALUES ('project-two', 'Project Two')"
        )
        await db.commit()

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

    async with aiosqlite.connect(database_path) as db:
        cursor = await db.execute(
            "SELECT project_id, relevance_score FROM project_articles ORDER BY project_id"
        )
        rows = await cursor.fetchall()
    assert rows == [(1, 0.9), (2, 0.4)]


@pytest.mark.asyncio
async def test_same_substantial_content_from_different_urls_is_deduplicated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "news.sqlite3"
    await Database(database_path).initialize()
    repository = ArticleRepository(database_path)
    first_article = normalize_article(
        url="https://one.example/story",
        title="Major museum announcement",
        description="The museum announced a significant new exhibition today.",
        content="The exhibition includes a substantial collection of works by artists "
        "from the nineteenth century and will remain open to visitors through November.",
    )
    second_article = normalize_article(
        url="https://two.example/copy",
        title="Major museum announcement",
        description="The museum announced a significant new exhibition today.",
        content="The exhibition includes a substantial collection of works by artists "
        "from the nineteenth century and will remain open to visitors through November.",
    )

    first = await repository.save_articles([first_article])
    second = await repository.save_articles([second_article])

    assert first[0].inserted is True
    assert second[0].inserted is False
    assert second[0].duplicate_of == first[0].article_id
    assert second[0].article_id == first[0].article_id


@pytest.mark.asyncio
async def test_short_articles_with_same_title_are_not_content_deduplicated(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "news.sqlite3"
    await Database(database_path).initialize()
    repository = ArticleRepository(database_path)
    first = normalize_article(
        url="https://one.example/story",
        title="Breaking news",
        description="Short",
    )
    second = normalize_article(
        url="https://two.example/story",
        title="Breaking news",
        description="Short",
    )

    saved = await repository.save_articles([first, second])

    assert saved[0].inserted is True
    assert saved[1].inserted is True
    assert saved[0].article_id != saved[1].article_id
