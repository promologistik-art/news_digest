"""Persistence helpers for shared sources/articles and project associations."""

"""Persistence helpers for shared sources/articles and project associations."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from news_digest.collection.normalization import NormalizedArticle


@dataclass(frozen=True, slots=True)
class StoredArticle:
    article_id: int
    canonical_url: str
    inserted: bool
    duplicate_of: int | None = None


async def _fetchone(
    db: aiosqlite.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> Any | None:
    cursor = await db.execute(query, parameters)
    return await cursor.fetchone()


class ArticleRepository:
    """Stores each source article once and links it independently to projects."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    async def register_source(
        self,
        *,
        url: str,
        name: str | None = None,
        source_type: str = "rss",
        reliability_score: float = 0.5,
    ) -> int:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO sources (url, name, source_type, reliability_score)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    name = COALESCE(excluded.name, sources.name),
                    source_type = excluded.source_type
                """,
                (url, name, source_type, reliability_score),
            )
            await db.commit()
            row = await _fetchone(db, "SELECT id FROM sources WHERE url = ?", (url,))
            if row is None:
                raise RuntimeError("Source insert completed but source ID was not found.")
            return int(row[0])

    async def save_articles(
        self,
        articles: Iterable[NormalizedArticle],
        *,
        source_id: int | None = None,
    ) -> list[StoredArticle]:
        stored: list[StoredArticle] = []
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("BEGIN")
            for article in articles:
                duplicate = await _fetchone(
                    db,
                    """
                    SELECT id, canonical_url
                    FROM articles
                    WHERE canonical_url = ? OR content_hash = ?
                    ORDER BY CASE WHEN canonical_url = ? THEN 0 ELSE 1 END
                    LIMIT 1
                    """,
                    (
                        article.canonical_url,
                        article.content_hash,
                        article.canonical_url,
                    ),
                )
                if duplicate is not None:
                    article_id = int(duplicate[0])
                    stored.append(
                        StoredArticle(
                            article_id=article_id,
                            canonical_url=article.canonical_url,
                            inserted=False,
                            duplicate_of=(
                                article_id
                                if str(duplicate[1]) != article.canonical_url
                                else None
                            ),
                        )
                    )
                    continue

                await db.execute(
                    """
                    INSERT INTO articles (
                        canonical_url, title, description, content, source_id,
                        published_at, content_hash, image_url
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(canonical_url) DO NOTHING
                    """,
                    (
                        article.canonical_url,
                        article.title,
                        article.description,
                        article.content,
                        source_id,
                        article.published_at,
                        article.content_hash,
                        article.image_url,
                    ),
                )
                row = await _fetchone(
                    db,
                    "SELECT id FROM articles WHERE canonical_url = ?",
                    (article.canonical_url,),
                )
                if row is None:
                    raise RuntimeError("Article insert completed but article ID was not found.")
                stored.append(
                    StoredArticle(
                        article_id=int(row[0]),
                        canonical_url=article.canonical_url,
                        inserted=True,
                    )
                )
            await db.commit()
        return stored

    async def attach_to_project(
        self,
        *,
        project_id: int,
        article_id: int,
        relevance_score: float | None = None,
    ) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO project_articles (project_id, article_id, relevance_score)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id, article_id) DO UPDATE SET
                    relevance_score = COALESCE(
                        excluded.relevance_score,
                        project_articles.relevance_score
                    )
                """,
                (project_id, article_id, relevance_score),
            )
            await db.commit()
