from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from news_digest.collection.normalization import normalize_article
from news_digest.editorial.models import EditorialBrief
from news_digest.editorial.service import EditorialService
from news_digest.storage.database import Database
from news_digest.storage.editorial_repository import EditorialRepository


class NoCallAI:
    async def chat(self, **_: object):
        raise AssertionError("AI must not be called after the project budget is exhausted.")


@pytest.mark.asyncio
async def test_zero_project_budget_blocks_ai_before_network_call(tmp_path: Path) -> None:
    database_path = tmp_path / "budget-block.sqlite3"
    await Database(database_path).initialize()
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            ("budget", "Budget"),
        )
        await db.execute(
            "INSERT INTO articles (canonical_url, title, content_hash) VALUES (?, ?, ?)",
            ("https://example.com/story", "News", "fingerprint"),
        )
        await db.execute(
            "INSERT INTO project_articles (project_id, article_id) VALUES (1, 1)"
        )
        await db.commit()

    article = normalize_article(
        url="https://example.com/story",
        title="News",
        description="A sufficiently detailed news summary for a test.",
    )
    brief = EditorialBrief(project_name="Budget", monthly_ai_budget_rub=0)
    repository = EditorialRepository(database_path)
    service = EditorialService(NoCallAI(), repository)

    result = await service.process_and_save(
        article, brief, project_id=1, article_id=1
    )

    assert result.draft is None
    assert "monthly AI budget" in (result.assessment.rejection_reason or "")
    async with aiosqlite.connect(database_path) as db:
        usage = await db.execute_fetchall("SELECT id FROM ai_usage")
        status = await db.execute_fetchall(
            "SELECT editorial_status FROM project_articles WHERE project_id=1 AND article_id=1"
        )
    assert usage == []
    assert status == [("rejected",)]
