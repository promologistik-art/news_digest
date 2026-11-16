from __future__ import annotations

import json

import aiosqlite
import pytest

from news_digest.editorial.models import EditorialAssessment, EditorialDraft
from news_digest.editorial.service import EditorialResult
from news_digest.storage.database import Database
from news_digest.storage.editorial_repository import EditorialRepository


@pytest.mark.asyncio
async def test_save_result_persists_project_decision_and_model_usage(tmp_path) -> None:
    database_path = tmp_path / "news.sqlite3"
    await Database(database_path).initialize()

    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            ("culture", "Culture"),
        )
        await connection.execute(
            """
            INSERT INTO articles (
                canonical_url, title, content_hash
            ) VALUES (?, ?, ?)
            """,
            ("https://example.com/story", "Story", "fingerprint"),
        )
        await connection.commit()

    result = EditorialResult(
        assessment=EditorialAssessment(
            relevant=True,
            topic="books",
            relevance_score=90,
            significance_score=80,
            novelty_score=70,
            confidence=95,
            factual_points=["A new book was announced."],
        ),
        draft=EditorialDraft(
            headline="New book announced",
            caption="A publisher announced a new book.",
            source_url="https://example.com/story",
            factual_points_used=["A new book was announced."],
        ),
        assessment_model="deepseek/flash",
        draft_model="deepseek/flash",
        assessment_tokens=120,
        draft_tokens=80,
    )

    await EditorialRepository(database_path).save_result(
        project_id=1,
        article_id=1,
        result=result,
    )

    async with aiosqlite.connect(database_path) as connection:
        article_cursor = await connection.execute(
            """
            SELECT relevance_score, significance_score, editorial_status,
                   editorial_payload
            FROM project_articles WHERE project_id = 1 AND article_id = 1
            """
        )
        article_row = await article_cursor.fetchone()
        usage_rows = await connection.execute_fetchall(
            """
            SELECT provider, model, operation, total_tokens
            FROM ai_usage WHERE project_id = 1 ORDER BY id
            """
        )

    assert article_row is not None
    assert article_row[:3] == (90, 80, "ready")
    payload = json.loads(article_row[3])
    assert payload["draft"]["headline"] == "New book announced"
    assert payload["assessment"]["topic"] == "books"
    assert usage_rows == [
        ("routerai", "deepseek/flash", "editorial_assessment", 120),
        ("routerai", "deepseek/flash", "editorial_draft", 80),
    ]
