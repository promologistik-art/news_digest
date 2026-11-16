"""RSS collection and persistence of normalized source articles."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any

import aiosqlite
import feedparser
import httpx

from news_digest.collection.normalization import normalize_article
from news_digest.config import Settings
from news_digest.storage.database import Database


@dataclass(frozen=True, slots=True)
class CollectedArticle:
    canonical_url: str
    title: str
    description: str
    content: str
    content_hash: str
    image_url: str | None
    published_at: str | None
    source_id: int
    language: str | None


class RSSCollector:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def collect_project(self, project_id: int, database: Database) -> int:
        async with aiosqlite.connect(database.path) as db:
            cursor = await db.execute(
                """
                SELECT s.id, s.url FROM sources s
                JOIN project_sources ps ON ps.source_id = s.id
                WHERE ps.project_id = ? AND ps.enabled = 1 AND s.is_active = 1
                ORDER BY s.id
                """,
                (project_id,),
            )
            sources = await cursor.fetchall()
        if not sources:
            return 0

        timeout = httpx.Timeout(self.settings.collection_timeout_seconds)
        headers = {"User-Agent": self.settings.collection_user_agent}
        async with httpx.AsyncClient(
            timeout=timeout, headers=headers, follow_redirects=True
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_feed(client, source_id, url) for source_id, url in sources),
                return_exceptions=True,
            )

        saved = 0
        async with aiosqlite.connect(database.path) as db:
            for result in results:
                if isinstance(result, Exception):
                    continue
                for article in result:
                    cursor = await db.execute(
                        """
                        INSERT INTO articles (
                            canonical_url, title, description, content, source_id,
                            language, published_at, content_hash, image_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_url) DO UPDATE SET
                            title=excluded.title, description=excluded.description,
                            content=CASE WHEN excluded.content != '' THEN excluded.content
                                         ELSE articles.content END,
                            image_url=COALESCE(excluded.image_url, articles.image_url)
                        """,
                        (
                            article.canonical_url, article.title, article.description,
                            article.content, article.source_id, article.language,
                            article.published_at, article.content_hash, article.image_url,
                        ),
                    )
                    lookup = await db.execute(
                        "SELECT id FROM articles WHERE canonical_url=?",
                        (article.canonical_url,),
                    )
                    article_id = (await lookup.fetchone())[0]
                    await db.execute(
                        """
                        INSERT INTO project_articles (project_id, article_id)
                        VALUES (?, ?) ON CONFLICT(project_id, article_id) DO NOTHING
                        """,
                        (project_id, article_id),
                    )
                    saved += int(cursor.rowcount == 1)
            await db.commit()
        return saved

    async def _fetch_feed(
        self, client: httpx.AsyncClient, source_id: int, url: str
    ) -> list[CollectedArticle]:
        response = await client.get(url)
        response.raise_for_status()
        parsed = feedparser.parse(response.content)
        output = []
        for entry in parsed.entries:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue
            contents = entry.get("content") or []
            content = contents[0].get("value", "") if contents else ""
            published = entry.get("published") or entry.get("updated")
            try:
                published_at = (
                    parsedate_to_datetime(published).astimezone(UTC).isoformat()
                    if published else None
                )
            except (TypeError, ValueError, OverflowError):
                published_at = None
            normalized = normalize_article(
                url=link, title=title, description=entry.get("summary"),
                content=content, published_at=published_at, image_url=_entry_image(entry),
            )
            output.append(
                CollectedArticle(
                    canonical_url=normalized.canonical_url, title=normalized.title,
                    description=normalized.description, content=normalized.content,
                    content_hash=normalized.content_hash, image_url=normalized.image_url,
                    published_at=normalized.published_at, source_id=source_id,
                    language=entry.get("language"),
                )
            )
        return output


def _entry_image(entry: Any) -> str | None:
    media = entry.get("media_content") or entry.get("media_thumbnail") or []
    for item in media:
        url = item.get("url")
        if url:
            return url
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and str(link.get("type", "")).startswith("image/"):
            return link.get("href")
    return None
