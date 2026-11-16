"""RSS/Atom collection with bounded redirects and public-host checks."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from dataclasses import dataclass
from datetime import UTC
from email.utils import format_datetime
from time import struct_time
from typing import Any, Self
from urllib.parse import urljoin, urlsplit

import feedparser
import aiosqlite
import httpx

from news_digest.collection.normalization import NormalizedArticle, normalize_article
from news_digest.config import Settings
from news_digest.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RSSSource:
    url: str
    name: str | None = None
    timeout_seconds: float = 25
    user_agent: str = "news_digest/0.1"
    max_redirects: int = 4


class RSSCollector:
    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> Self:
        if self._client is None:
            self._client = httpx.AsyncClient(follow_redirects=False)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def collect(self, source: RSSSource) -> list[NormalizedArticle]:
        await _validate_public_url(source.url)
        client = self._client
        temporary_client = client is None
        if temporary_client:
            client = httpx.AsyncClient(follow_redirects=False)
        assert client is not None
        try:
            response = await self._get_with_redirects(client, source)
            response.raise_for_status()
            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"Invalid RSS/Atom feed: {source.url}")
            articles: list[NormalizedArticle] = []
            for entry in parsed.entries:
                article = _entry_to_article(entry)
                if article is not None:
                    articles.append(article)
            logger.info(
                "Collected %d entries from RSS source %s",
                len(articles),
                source.name or source.url,
            )
            return articles
        finally:
            if temporary_client:
                await client.aclose()


    async def collect_project(
        self, project_id: int, database: Database, settings: Settings
    ) -> int:
        """Collect feeds assigned to a project and attach normalized articles to it."""
        async with aiosqlite.connect(database.path) as db:
            cursor = await db.execute(
                """
                SELECT s.id, s.url, s.name FROM sources s
                JOIN project_sources ps ON ps.source_id = s.id
                WHERE ps.project_id = ? AND ps.enabled = 1 AND s.is_active = 1
                ORDER BY s.id
                """,
                (project_id,),
            )
            sources = await cursor.fetchall()

        saved = 0
        for source_id, url, name in sources:
            source = RSSSource(
                url=url,
                name=name,
                timeout_seconds=settings.collection_timeout_seconds,
                user_agent=settings.collection_user_agent,
            )
            try:
                articles = await self.collect(source)
            except (httpx.HTTPError, ValueError, OSError) as exc:
                logger.warning("RSS source failed (%s): %s", name or url, type(exc).__name__)
                continue
            async with aiosqlite.connect(database.path) as db:
                for article in articles:
                    cursor = await db.execute(
                        """
                        INSERT INTO articles (
                            canonical_url, title, description, content, source_id,
                            published_at, content_hash, image_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(canonical_url) DO UPDATE SET
                            title=excluded.title, description=excluded.description,
                            content=CASE WHEN excluded.content != ''
                                         THEN excluded.content ELSE articles.content END,
                            image_url=COALESCE(excluded.image_url, articles.image_url)
                        """,
                        (
                            article.canonical_url, article.title, article.description,
                            article.content, source_id, article.published_at,
                            article.content_hash, article.image_url,
                        ),
                    )
                    lookup = await db.execute(
                        "SELECT id FROM articles WHERE canonical_url = ?",
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

    async def _get_with_redirects(
        self,
        client: httpx.AsyncClient,
        source: RSSSource,
    ) -> httpx.Response:
        url = source.url
        headers = {
            "User-Agent": source.user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml, text/xml, */*",
        }
        for redirect_count in range(source.max_redirects + 1):
            await _validate_public_url(url)
            response = await client.get(
                url,
                headers=headers,
                timeout=source.timeout_seconds,
            )
            if response.status_code not in {301, 302, 303, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                raise ValueError("Feed redirect did not include a Location header.")
            if redirect_count >= source.max_redirects:
                raise ValueError("Feed exceeded the maximum redirect count.")
            url = str(response.url.join(location))
        raise ValueError("Feed redirect handling failed.")


async def _validate_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Feed URL must be an absolute HTTP(S) URL.")
    if parts.username or parts.password:
        raise ValueError("Credentials are not allowed in feed URLs.")
    host = parts.hostname.lower().rstrip(".")
    if host in {"localhost"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("Private and local feed hosts are not allowed.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            records = await asyncio.to_thread(
                socket.getaddrinfo,
                host,
                parts.port or (443 if parts.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as exc:
            raise ValueError(f"Unable to resolve feed host: {host}") from exc
        addresses = [ipaddress.ip_address(record[4][0]) for record in records]
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Feed URL resolves to a non-public IP address.")


def _entry_to_article(entry: Any) -> NormalizedArticle | None:
    title = entry.get("title", "")
    link = entry.get("link", "")
    if not title or not link:
        return None

    description = entry.get("summary", "")
    content_items = entry.get("content") or []
    content = content_items[0].get("value", "") if content_items else description
    published_at = _published_at(entry)
    image_url = _image_url(entry)
    if image_url:
        image_url = urljoin(link, image_url)
    try:
        return normalize_article(
            url=link,
            title=title,
            description=description,
            content=content,
            published_at=published_at,
            image_url=image_url,
        )
    except ValueError:
        logger.warning("Skipping malformed RSS entry URL: %s", link)
        return None


def _published_at(entry: Any) -> str | None:
    parsed: struct_time | None = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed is None:
        return None
    from datetime import datetime

    return format_datetime(datetime(*parsed[:6], tzinfo=UTC))


def _image_url(entry: Any) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        values = entry.get(key) or []
        for value in values:
            candidate = value.get("url")
            if candidate:
                return str(candidate)
    for enclosure in entry.get("enclosures") or []:
        media_type = enclosure.get("type", "")
        if media_type.startswith("image/") and enclosure.get("href"):
            return str(enclosure["href"])
    return None
