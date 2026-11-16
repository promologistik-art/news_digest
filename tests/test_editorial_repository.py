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

    assert article_row is not None
    assert article_row[:3] == (90, 80, "ready")
    payload = json.loads(article_row[3])
    assert payload["draft"]["headline"] == "New book announced"
    assert payload["assessment"]["topic"] == "books"
    assert article_row[2] == "ready"



@pytest.mark.asyncio
async def test_ai_budget_reservation_and_actual_cost_accounting(tmp_path) -> None:
    database_path = tmp_path / "usage.sqlite3"
    await Database(database_path).initialize()
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            ("budget", "Budget"),
        )
        await connection.commit()

    repository = EditorialRepository(database_path)
    reservation = await repository.reserve_ai_budget(
        project_id=1,
        operation="editorial_assessment",
        estimated_cost=0.04,
        monthly_budget=0.05,
    )
    assert reservation is not None
    assert await repository.reserve_ai_budget(
        project_id=1,
        operation="editorial_draft",
        estimated_cost=0.02,
        monthly_budget=0.05,
    ) is None

    cost = await repository.record_ai_usage(
        project_id=1,
        provider="routerai",
        model="deepseek/flash",
        operation="editorial_assessment",
        input_tokens=1000,
        output_tokens=500,
        total_tokens=1500,
        input_price_per_million=11,
        output_price_per_million=45,
        currency="RUB",
        request_id="req-1",
        reservation_id=reservation,
        estimated_cost=0.04,
    )
    assert cost == pytest.approx(0.0335)

    usage = await repository.get_monthly_usage(project_id=1)
    assert usage == {
        "requests": 1,
        "input_tokens": 1000,
        "output_tokens": 500,
        "total_tokens": 1500,
        "cost": pytest.approx(0.0335),
        "estimated_requests": 0,
    }
    assert await repository.reserve_ai_budget(
        project_id=1,
        operation="editorial_draft",
        estimated_cost=0.02,
        monthly_budget=0.05,
    ) is None


@pytest.mark.asyncio
async def test_usage_without_provider_token_counts_is_marked_estimated(tmp_path) -> None:
    database_path = tmp_path / "estimated-usage.sqlite3"
    await Database(database_path).initialize()
    async with aiosqlite.connect(database_path) as connection:
        await connection.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            ("estimated", "Estimated"),
        )
        await connection.commit()

    repository = EditorialRepository(database_path)
    await repository.record_ai_usage(
        project_id=1,
        provider="routerai",
        model="deepseek/flash",
        operation="editorial_assessment",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        input_price_per_million=11,
        output_price_per_million=45,
        currency="RUB",
        request_id=None,
        estimated_cost=0.01,
    )
    usage = await repository.get_monthly_usage(project_id=1)
    assert usage["cost"] == pytest.approx(0.01)
    assert usage["estimated_requests"] == 1
