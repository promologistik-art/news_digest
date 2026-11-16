"""Two-stage editorial pipeline: assess first, draft only selected articles."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from news_digest.ai.routerai import RouterAIClient
from news_digest.collection.normalization import NormalizedArticle
from news_digest.editorial.models import EditorialAssessment, EditorialBrief, EditorialDraft
from news_digest.storage.editorial_repository import EditorialRepository

logger = logging.getLogger(__name__)


class EditorialError(RuntimeError):
    """Editorial response could not be safely interpreted."""


@dataclass(frozen=True, slots=True)
class EditorialResult:
    assessment: EditorialAssessment
    draft: EditorialDraft | None
    assessment_model: str
    draft_model: str | None
    assessment_tokens: int | None
    draft_tokens: int | None


class EditorialService:
    """Runs independent editorial decisions for each project's own brief."""

    def __init__(
        self,
        ai: RouterAIClient,
        repository: EditorialRepository | None = None,
    ) -> None:
        self.ai = ai
        self.repository = repository

    async def process_and_save(
        self,
        article: NormalizedArticle,
        brief: EditorialBrief,
        *,
        project_id: int,
        article_id: int,
    ) -> EditorialResult:
        """Run editorial processing and persist the outcome and token usage."""
        if self.repository is None:
            raise EditorialError("EditorialRepository is required to persist results.")
        result = await self.process(article, brief)
        await self.repository.save_result(
            project_id=project_id,
            article_id=article_id,
            result=result,
        )
        return result

    async def process(
        self,
        article: NormalizedArticle,
        brief: EditorialBrief,
    ) -> EditorialResult:
        rejection = _preflight_rejection(article, brief)
        if rejection is not None:
            return EditorialResult(
                assessment=EditorialAssessment(
                    relevant=False, topic="", relevance_score=0,
                    significance_score=0, novelty_score=0, confidence=100,
                    rejection_reason=rejection,
                ),
                draft=None, assessment_model="deterministic_rules",
                draft_model=None, assessment_tokens=None, draft_tokens=None,
            )

        assessed = await self.ai.chat(
            operation="editorial_assessment",
            temperature=0.1,
            max_tokens=900,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты редактор новостного проекта. Оценивай только предоставленные данные. "
                        "Не додумывай факты. Верни JSON со всеми полями: relevant, topic, geography, "
                        "relevance_score, significance_score, novelty_score, confidence, article_date, "
                        "event_date, factual_points, uncertainties, rejection_reason. "
                        "Оценки от 0 до 100, даты ISO 8601 или null."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"project": brief.model_dump(), "article": _article_payload(article)},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        assessment = _parse_model(EditorialAssessment, assessed.content)
        selected = (
            assessment.relevant
            and assessment.relevance_score >= 50
            and assessment.significance_score >= brief.min_significance
            and assessment.confidence >= 45
        )
        if not selected:
            return EditorialResult(
                assessment=assessment,
                draft=None,
                assessment_model=assessed.model,
                draft_model=None,
                assessment_tokens=_total_tokens(assessed.usage),
                draft_tokens=None,
            )

        drafted = await self.ai.chat(
            operation="editorial_draft",
            temperature=0.3,
            max_tokens=700,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Подготовь новостную публикацию на языке проекта. Используй только факты "
                        "из исходной статьи и factual_points оценки. Не добавляй внешние сведения, "
                        "причины, прогнозы или цитаты. Если данных недостаточно, обозначь это "
                        "в caveat. Верни JSON: headline, caption, source_url, factual_points_used, "
                        "caveat. Заголовок и подпись должны быть содержательными, без кликбейта."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "project": brief.model_dump(),
                            "article": _article_payload(article),
                            "assessment": assessment.model_dump(),
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        draft = _parse_model(EditorialDraft, drafted.content)
        if str(draft.source_url).rstrip("/") != article.canonical_url.rstrip("/"):
            raise EditorialError("Draft source_url does not match the supplied source article.")
        return EditorialResult(
            assessment=assessment,
            draft=draft,
            assessment_model=assessed.model,
            draft_model=drafted.model,
            assessment_tokens=_total_tokens(assessed.usage),
            draft_tokens=_total_tokens(drafted.usage),
        )


def _article_payload(article: NormalizedArticle) -> dict[str, Any]:
    return {
        "url": article.canonical_url,
        "title": article.title,
        "description": article.description,
        "content": article.content[:12000],
        "published_at": article.published_at,
    }


def _parse_model(model: type[Any], content: str) -> Any:
    cleaned = content.strip()
    if cleaned.startswith(chr(96) * 3):
        cleaned = cleaned.removeprefix(chr(96) * 3 + "json")
        cleaned = cleaned.removeprefix(chr(96) * 3).removesuffix(chr(96) * 3).strip()
    try:
        return model.model_validate(json.loads(cleaned))
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        logger.warning("AI returned invalid editorial JSON: %s", type(exc).__name__)
        raise EditorialError(
            "AI returned an invalid editorial response; article was not selected."
        ) from exc


def _total_tokens(usage: Any) -> int | None:
    return usage.total_tokens if usage is not None else None


def _preflight_rejection(article: NormalizedArticle, brief: EditorialBrief, *, now: datetime | None = None) -> str | None:
    """Reject clearly stale or explicitly excluded material before spending AI tokens."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if article.published_at:
        try:
            published = datetime.fromisoformat(article.published_at.strip().replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            age = current - published.astimezone(UTC)
        except (TypeError, ValueError):
            logger.warning("Article has an unparseable publication date; freshness check skipped: %s", article.canonical_url)
        else:
            if age > timedelta(hours=brief.max_age_hours):
                return f"Article is older than the project limit ({brief.max_age_hours} hours)."
            if age < timedelta(hours=-6):
                return "Article publication date is more than 6 hours in the future."
    searchable_text = " ".join((article.title, article.description, article.content)).casefold()
    for excluded in brief.excluded_topics:
        term = " ".join(excluded.split()).casefold()
        if term and term in searchable_text:
            return f"Article matches an excluded topic: {excluded}."
    return None