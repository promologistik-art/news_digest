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
        """Upsert the assessment and generated draft for a project article."""
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
            await connection.commit()


    async def reserve_ai_budget(
        self,
        *,
        project_id: int,
        operation: str,
        estimated_cost: float,
        monthly_budget: float,
        currency: str = "RUB",
    ) -> int | None:
        """Atomically reserve estimated spend against the project's monthly budget."""
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        start_text = month_start.strftime("%Y-%m-%d %H:%M:%S")
        end_text = next_month.strftime("%Y-%m-%d %H:%M:%S")
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            spent_cursor = await db.execute(
                """
                SELECT COALESCE(SUM(cost_amount), 0) FROM ai_usage
                WHERE project_id=? AND cost_currency=?
                  AND created_at>=? AND created_at<?
                """,
                (project_id, currency, start_text, end_text),
            )
            spent = float((await spent_cursor.fetchone())[0] or 0)
            reserved_cursor = await db.execute(
                """
                SELECT COALESCE(SUM(reserved_amount), 0)
                FROM ai_budget_reservations
                WHERE project_id=? AND status='reserved' AND created_at>=? AND created_at<?
                """,
                (project_id, start_text, end_text),
            )
            reserved = float((await reserved_cursor.fetchone())[0] or 0)
            if spent + reserved + estimated_cost > monthly_budget:
                await db.rollback()
                return None
            cursor = await db.execute(
                """
                INSERT INTO ai_budget_reservations
                    (project_id, operation, reserved_amount, status)
                VALUES (?, ?, ?, 'reserved')
                """,
                (project_id, operation, estimated_cost),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def release_ai_budget(self, *, reservation_id: int) -> None:
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                UPDATE ai_budget_reservations
                SET status='released', completed_at=CURRENT_TIMESTAMP
                WHERE id=? AND status='reserved'
                """,
                (reservation_id,),
            )
            await db.commit()

    async def record_ai_usage(
        self,
        *,
        project_id: int,
        provider: str,
        model: str,
        operation: str,
        input_tokens: int | None,
        output_tokens: int | None,
        total_tokens: int | None,
        input_price_per_million: float,
        output_price_per_million: float,
        currency: str,
        request_id: str | None,
        reservation_id: int | None = None,
        estimated_cost: float = 0.0,
    ) -> float:
        """Persist actual token usage and settle a reservation; estimate only if usage is absent."""
        has_usage = input_tokens is not None and output_tokens is not None
        cost = (
            (
                input_tokens * input_price_per_million
                + output_tokens * output_price_per_million
            )
            / 1_000_000
            if has_usage
            else estimated_cost
        )
        async with aiosqlite.connect(self.database_path) as db:
            await db.execute(
                """
                INSERT INTO ai_usage (
                    project_id, provider, model, operation, input_tokens,
                    output_tokens, total_tokens, cost_amount, cost_currency,
                    cost_estimated, request_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_id,
                    provider,
                    model,
                    operation,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    cost,
                    currency,
                    int(not has_usage),
                    request_id,
                ),
            )
            if reservation_id is not None:
                await db.execute(
                    """
                    UPDATE ai_budget_reservations
                    SET status='completed', completed_at=CURRENT_TIMESTAMP
                    WHERE id=? AND status='reserved'
                    """,
                    (reservation_id,),
                )
            await db.commit()
        return cost

    async def get_monthly_usage(
        self, *, project_id: int, currency: str = "RUB"
    ) -> dict[str, int | float]:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        async with aiosqlite.connect(self.database_path) as db:
            cursor = await db.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(input_tokens), 0),
                       COALESCE(SUM(output_tokens), 0),
                       COALESCE(SUM(total_tokens), 0),
                       COALESCE(SUM(cost_amount), 0),
                       COALESCE(SUM(cost_estimated), 0)
                FROM ai_usage
                WHERE project_id=? AND cost_currency=?
                  AND created_at>=? AND created_at<?
                """,
                (
                    project_id,
                    currency,
                    month_start.strftime("%Y-%m-%d %H:%M:%S"),
                    next_month.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            row = await cursor.fetchone()
        return {
            "requests": int(row[0]),
            "input_tokens": int(row[1]),
            "output_tokens": int(row[2]),
            "total_tokens": int(row[3]),
            "cost": float(row[4]),
            "estimated_requests": int(row[5]),
        }
