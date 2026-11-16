"""Persist project-specific editorial decisions and RouterAI token usage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

if TYPE_CHECKING:
    from news_digest.editorial.service import EditorialResult


class EditorialRepository:
    """Stores the editorial outcome against a project's normalized article."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = database_path

    async def save_result(
        self,
        *,
        project_id: int,
        article_id: int,
        result: EditorialResult,
    ) -> None:
        """Upsert the assessment/draft and record each model operation's usage."""
        payload = {
            "assessment": result.assessment.model_dump(mode="json"),
            "draft": result.draft.model_dump(mode="json") if result.draft else None,
            "assessment_model": result.assessment_model,
            "draft_model": result.draft_model,
            "assessment_tokens": result.assessment_tokens,
            "draft_tokens": result.draft_tokens,
        }
        status = "ready" if result.draft is not None else "rejected"
        async with aiosqlite.connect(self.database_path) as connection:
            await connection.execute(
                """
                INSERT INTO project_articles (
                    project_id, article_id, relevance_score, significance_score,
                    editorial_status, editorial_payload
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, article_id) DO UPDATE SET
                    relevance_score = excluded.relevance_score,
                    significance_score = excluded.significance_score,
                    editorial_status = excluded.editorial_status,
                    editorial_payload = excluded.editorial_payload
                """,
                (
                    project_id,
                    article_id,
                    result.assessment.relevance_score,
                    result.assessment.significance_score,
                    status,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            await connection.execute(
                """
                INSERT INTO ai_usage (
                    project_id, provider, model, operation, total_tokens, request_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    "routerai",
                    result.assessment_model,
                    "editorial_assessment",
                    result.assessment_tokens,
                    None,
                ),
            )
            if result.draft is not None and result.draft_model is not None:
                await connection.execute(
                    """
                    INSERT INTO ai_usage (
                        project_id, provider, model, operation, total_tokens, request_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        "routerai",
                        result.draft_model,
                        "editorial_draft",
                        result.draft_tokens,
                        None,
                    ),
                )
            await connection.commit()
