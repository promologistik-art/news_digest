"""One-shot orchestration for collection, project-specific editorial and publishing."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

import aiosqlite

from news_digest.ai.routerai import RouterAIClient, RouterAIError
from news_digest.collection.normalization import NormalizedArticle
from news_digest.collection.rss import RSSCollector
from news_digest.config import Settings
from news_digest.editorial.models import EditorialBrief
from news_digest.editorial.service import EditorialError, EditorialService
from news_digest.publishing.telegram import TelegramPublisher
from news_digest.storage.database import Database
from news_digest.storage.editorial_repository import EditorialRepository
from news_digest.storage.publication_queue import PublicationQueue

logger = logging.getLogger(__name__)


async def run_once(\n    settings: Settings, *, project_id: int | None = None\n) -> dict[str, int]:
    database = Database(settings.database_path)
    await database.initialize()
    queue = PublicationQueue(settings.database_path)
    collector = RSSCollector()
    totals = {"collected": 0, "assessed": 0, "queued": 0, "published": 0, "failed": 0}

    async with aiosqlite.connect(settings.database_path) as db:
        if project_id is None:
            projects = await db.execute_fetchall(
                "SELECT id, name, language FROM projects WHERE status = 'active' ORDER BY id"
            )
        else:
            projects = await db.execute_fetchall(
                "SELECT id, name, language FROM projects "
                "WHERE status = 'active' AND id = ? ORDER BY id",
                (project_id,),
            )

    async with RouterAIClient(settings) as ai:
        editorial = EditorialService(ai, EditorialRepository(settings.database_path))
        for project_id, project_name, language in projects:
            totals["collected"] += await collector.collect_project(project_id, database, settings)
            async with aiosqlite.connect(settings.database_path) as db:
                rules_cursor = await db.execute(
                    "SELECT rules_json FROM project_rules WHERE project_id=?", (project_id,)
                )
                rules_row = await rules_cursor.fetchone()
                articles_cursor = await db.execute(
                    """
                    SELECT a.id, a.canonical_url, a.title, a.description, a.content,
                           a.published_at, a.image_url, a.content_hash
                    FROM articles a JOIN project_articles pa ON pa.article_id=a.id
                    WHERE pa.project_id=? AND pa.editorial_status='new'
                    ORDER BY COALESCE(a.published_at, a.collected_at) DESC LIMIT 100
                    """,
                    (project_id,),
                )
                articles = await articles_cursor.fetchall()
            rules = json.loads(rules_row[0]) if rules_row else {}
            brief = EditorialBrief(
                project_name=project_name, language=language,
                topics=rules.get("topics", []), geographies=rules.get("geographies", []),
                audience=rules.get("audience", ""),
                style_guide=rules.get(
                    "style_guide", "Пиши ясно, содержательно и без кликбейта."
                ),
                excluded_topics=rules.get("excluded_topics", []),
                min_significance=rules.get("min_significance", 55),
                max_age_hours=rules.get("max_age_hours", 72),
            )
            for row in articles:
                article_id, url, title, description, content, published_at, image_url, fingerprint = row
                article = NormalizedArticle(
                    canonical_url=url, title=title, description=description or "",
                    content=content or "", published_at=published_at, image_url=image_url,
                    content_hash=fingerprint,
                )
                try:
                    result = await editorial.process_and_save(
                        article, brief, project_id=project_id, article_id=article_id
                    )
                    totals["assessed"] += 1
                    if result.draft is not None and await queue.enqueue(
                        project_id=project_id, article_id=article_id
                    ):
                        totals["queued"] += 1
                except (RouterAIError, EditorialError, sqlite3.Error, ValueError):
                    logger.exception(
                        "Editorial processing failed for project=%s article=%s",
                        project_id, article_id,
                    )

    if settings.telegram_publishing_enabled:
        publisher = TelegramPublisher(settings.telegram_bot_token.get_secret_value(), queue)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        while True:
            item = await queue.claim_next(now=now)
            if item is None:
                break
            sent, failed = await publisher.publish(item)
            totals["published"] += sent
            totals["failed"] += failed
            if failed:
                break
    return totals
