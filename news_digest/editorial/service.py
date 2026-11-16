"""Two-stage editorial pipeline: assess first, draft only selected articles."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from news_digest.ai.routerai import RouterAIClient
from news_digest.collection.normalization import NormalizedArticle
from news_digest.editorial.models import EditorialAssessment, EditorialBrief, EditorialDraft

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

    def __init__(self, ai: RouterAIClient) -> None:
        self.ai = ai

    async def process(
        self,
        article: NormalizedArticle,
        brief: EditorialBrief,
    ) -> EditorialResult:
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
    if cleaned.startswith(""):
        cleaned = cleaned.strip()
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
