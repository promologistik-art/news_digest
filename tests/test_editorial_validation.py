from __future__ import annotations

from news_digest.collection.normalization import normalize_article
from news_digest.editorial.models import EditorialAssessment, EditorialBrief, EditorialDraft
from news_digest.editorial.service import (
    _validate_assessment_scope,
    _validate_draft,
    _validate_source_facts,
)


def _article():
    return normalize_article(
        url="https://example.com/news",
        title="Эрмитаж открыл выставку",
        description="Выставка посвящена русскому искусству.",
        content="В экспозиции представлены 25 картин художников XIX века. "
        "Выставка открыта до 30 ноября.",
        published_at="2026-11-16T08:00:00+00:00",
    )


def _assessment(**overrides):
    values = {
        "relevant": True,
        "topic": "Искусство",
        "geography": "Россия",
        "relevance_score": 90,
        "significance_score": 85,
        "novelty_score": 80,
        "confidence": 95,
        "factual_points": [
            "В экспозиции представлены 25 картин художников XIX века.",
            "Выставка открыта до 30 ноября.",
        ],
    }
    values.update(overrides)
    return EditorialAssessment(**values)


def _draft(**overrides):
    values = {
        "headline": "В Эрмитаже открылась выставка русского искусства",
        "caption": "В экспозиции представлены 25 картин художников XIX века. "
        "Выставка открыта до 30 ноября.",
        "source_url": "https://example.com/news",
        "factual_points_used": [
            "В экспозиции представлены 25 картин художников XIX века.",
        ],
    }
    values.update(overrides)
    return EditorialDraft(**values)


def test_assessment_topic_must_match_project_topic() -> None:
    brief = EditorialBrief(project_name="Culture", topics=["Кино", "Искусство"])
    assert _validate_assessment_scope(_assessment(topic="Политика"), brief) is not None


def test_assessment_accepts_configured_topic_case_insensitively() -> None:
    brief = EditorialBrief(project_name="Culture", topics=["Искусство"])
    assert _validate_assessment_scope(_assessment(topic="ИСКУССТВО"), brief) is None


def test_assessment_geography_must_match_project_geography() -> None:
    brief = EditorialBrief(project_name="Culture", geographies=["Россия"])
    assert _validate_assessment_scope(_assessment(geography="Германия"), brief) is not None


def test_assessment_requires_geography_when_project_configures_it() -> None:
    brief = EditorialBrief(project_name="Culture", geographies=["Россия"])
    assert _validate_assessment_scope(_assessment(geography=None), brief) is not None


def test_assessment_factual_points_must_be_source_excerpts() -> None:
    article = _article()
    valid = _assessment().factual_points
    invalid = [*valid, "В музей пришли 5000 посетителей."]
    assert _validate_source_facts(article, valid) is None
    assert _validate_source_facts(article, invalid) is not None


def test_draft_must_use_only_assessed_source_points() -> None:
    article = _article()
    assessment = _assessment()
    draft = _draft(
        factual_points_used=["В музей пришли 5000 посетителей."]
    )
    assert _validate_draft(article, assessment, draft) is not None


def test_draft_cannot_introduce_unsupported_numbers() -> None:
    article = _article()
    assessment = _assessment()
    draft = _draft(caption="В экспозиции представлены 250 картин.")
    assert _validate_draft(article, assessment, draft) is not None


def test_draft_with_source_supported_numbers_and_points_is_accepted() -> None:
    assert _validate_draft(_article(), _assessment(), _draft()) is None
