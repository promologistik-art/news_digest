"""Two-stage editorial pipeline: assess first, draft only selected articles."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from news_digest.ai.routerai import RouterAIClient
from news_digest.collection.normalization import NormalizedArticle
from news_digest.editorial.models import EditorialAssessment, EditorialBrief, EditorialDraft
from news_digest.storage.editorial_repository import EditorialRepository

logger = logging.getLogger(__name__)

_NUMBER_PATTERN = re.compile(r"(?<![\w])\d+(?:[.,]\d+)?(?![\w])")


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
            return _rejected_result(rejection)

        assessed = await self.ai.chat(
            operation="editorial_assessment",
            temperature=0.1,
            max_tokens=1100,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты редактор новостного проекта. Оценивай только предоставленные данные. "
                        "Не додумывай факты. Если список тем проекта не пуст, поле topic должно "
                        "дословно совпадать с одной из тем проекта. Если список географий не пуст, "
                        "поле geography должно дословно совпадать с одной из географий проекта; "
                        "если география статьи не подтверждается источником, укажи null. "
                        "factual_points — от 1 до 8 коротких дословных фрагментов исходной статьи, "
                        "подтверждающих основные факты; не пересказывай их своими словами. "
                        "Верни JSON со всеми полями: relevant, topic, geography, relevance_score, "
                        "significance_score, novelty_score, confidence, article_date, event_date, "
                        "factual_points, uncertainties, rejection_reason. Оценки от 0 до 100, "
                        "даты ISO 8601 или null."
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

        rejection = _validate_assessment_scope(assessment, brief)
        if rejection is None:
            rejection = _validate_source_facts(article, assessment.factual_points)
        if rejection is not None:
            return _rejected_result(
                rejection,
                assessment=assessment,
                model=assessed.model,
                tokens=_total_tokens(assessed.usage),
            )

        drafted = await self.ai.chat(
            operation="editorial_draft",
            temperature=0.2,
            max_tokens=700,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Подготовь новостную публикацию на языке проекта. Используй только факты "
                        "из исходной статьи и factual_points оценки. Не добавляй внешние сведения, "
                        "причины, прогнозы или цитаты. factual_points_used должен содержать только "
                        "дословные элементы из factual_points оценки, на которых основан текст. "
                        "Если данных недостаточно, обозначь это в caveat. Верни JSON: headline, "
                        "caption, source_url, factual_points_used, caveat. Заголовок и подпись "
                        "должны быть содержательными, без кликбейта."
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
        rejection = _validate_draft(article, assessment, draft)
        if rejection is not None:
            return _rejected_result(
                rejection,
                assessment=assessment,
                model=assessed.model,
                tokens=_total_tokens(assessed.usage),
            )
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


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().split())


def _validate_assessment_scope(
    assessment: EditorialAssessment,
    brief: EditorialBrief,
) -> str | None:
    """Require the model's topic and geography labels to belong to the project taxonomy."""
    if brief.topics:
        allowed_topics = {_normalized_text(item) for item in brief.topics}
        if _normalized_text(assessment.topic) not in allowed_topics:
            return "Assessment topic is outside the project's configured topics."
    if brief.geographies:
        allowed_geographies = {_normalized_text(item) for item in brief.geographies}
        geography = _normalized_text(assessment.geography or "")
        if geography not in allowed_geographies:
            return "Assessment geography is outside the project's configured geographies."
    return None


def _validate_source_facts(
    article: NormalizedArticle,
    factual_points: list[str],
) -> str | None:
    """Require assessment evidence to be copied from the supplied source text."""
    source_text = _normalized_text(
        f"{article.title} {article.description} {article.content}"
    )
    if not factual_points:
        return "Assessment contains no source excerpts to support the draft."
    for point in factual_points:
        excerpt = _normalized_text(point)
        if len(excerpt) < 12 or excerpt not in source_text:
            return "Assessment contains a factual point that cannot be found in the source."
        if not _numbers_are_supported(point, source_text):
            return "Assessment factual point contains a number absent from the source."
    return None


def _validate_draft(
    article: NormalizedArticle,
    assessment: EditorialAssessment,
    draft: EditorialDraft,
) -> str | None:
    """Reject draft claims not traceable to assessed source excerpts or source numbers."""
    approved_points = {_normalized_text(point) for point in assessment.factual_points}
    used_points = {_normalized_text(point) for point in draft.factual_points_used}
    if not used_points or not used_points.issubset(approved_points):
        return "Draft uses factual points that were not approved from the source."
    source_text = _normalized_text(
        f"{article.title} {article.description} {article.content} {article.published_at or ''}"
    )
    evidence_text = f"{source_text} {' '.join(assessment.factual_points)}"
    draft_text = f"{draft.headline} {draft.caption}"
    if not _numbers_are_supported(draft_text, evidence_text):
        return "Draft contains a number or date that is absent from the source evidence."
    return None


def _numbers_are_supported(claim: str, evidence: str) -> bool:
    claim_numbers = {
        _normalize_number(value) for value in _NUMBER_PATTERN.findall(claim)
    }
    evidence_numbers = {
        _normalize_number(value) for value in _NUMBER_PATTERN.findall(evidence)
    }
    return claim_numbers.issubset(evidence_numbers)


def _normalize_number(value: str) -> str:
    normalized = value.replace(",", ".")
    if normalized.startswith("."):
        normalized = f"0{normalized}"
    return normalized.lstrip("0") or "0"


def _rejected_result(
    reason: str,
    *,
    assessment: EditorialAssessment | None = None,
    model: str = "deterministic_rules",
    tokens: int | None = None,
) -> EditorialResult:
    rejected = (
        assessment.model_copy(update={"relevant": False, "rejection_reason": reason})
        if assessment is not None
        else EditorialAssessment(
            relevant=False,
            topic="",
            relevance_score=0,
            significance_score=0,
            novelty_score=0,
            confidence=100,
            rejection_reason=reason,
        )
    )
    return EditorialResult(
        assessment=rejected,
        draft=None,
        assessment_model=model,
        draft_model=None,
        assessment_tokens=tokens,
        draft_tokens=None,
    )


def _preflight_rejection(
    article: NormalizedArticle,
    brief: EditorialBrief,
    *,
    now: datetime | None = None,
) -> str | None:
    """Reject clearly stale or explicitly excluded material before spending AI tokens."""
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if article.published_at:
        try:
            published = datetime.fromisoformat(article.published_at.strip())
            if published.tzinfo is None:
                published = published.replace(tzinfo=UTC)
            age = current - published.astimezone(UTC)
        except (TypeError, ValueError):
            logger.warning(
                "Article has an unparseable publication date; freshness check skipped: %s",
                article.canonical_url,
            )
        else:
            if age > timedelta(hours=brief.max_age_hours):
                return f"Article is older than the project limit ({brief.max_age_hours} hours)."
            if age < timedelta(hours=-6):
                return "Article publication date is more than 6 hours in the future."
    searchable_text = f"{article.title} {article.description} {article.content}".casefold()
    for excluded in brief.excluded_topics:
        term = " ".join(excluded.split()).casefold()
        if term and term in searchable_text:
            return f"Article matches an excluded topic: {excluded}."
    return None
