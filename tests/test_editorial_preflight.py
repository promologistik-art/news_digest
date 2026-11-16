from __future__ import annotations

from datetime import UTC, datetime, timedelta

from news_digest.collection.normalization import normalize_article
from news_digest.editorial.models import EditorialBrief
from news_digest.editorial.service import _preflight_rejection


def _article(*, published_at: str | None, title: str = "Новая выставка"):
    return normalize_article(
        url="https://example.com/news",
        title=title,
        description="Культурные новости",
        published_at=published_at,
    )


def test_preflight_rejects_article_older_than_project_limit() -> None:
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    published = (now - timedelta(hours=73)).isoformat()
    brief = EditorialBrief(project_name="Culture", max_age_hours=72)
    reason = _preflight_rejection(_article(published_at=published), brief, now=now)
    assert reason is not None
    assert "older" in reason


def test_preflight_accepts_article_inside_project_limit() -> None:
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    published = (now - timedelta(hours=71)).isoformat()
    brief = EditorialBrief(project_name="Culture", max_age_hours=72)
    assert _preflight_rejection(
        _article(published_at=published), brief, now=now
    ) is None


def test_preflight_rejects_explicitly_excluded_topic_case_insensitively() -> None:
    brief = EditorialBrief(project_name="Culture", excluded_topics=["криптовалюта"])
    reason = _preflight_rejection(
        _article(published_at=None, title="КРИПТОВАЛЮТА снова в новостях"), brief
    )
    assert reason == "Article matches an excluded topic: криптовалюта."


def test_preflight_does_not_reject_unknown_publication_date() -> None:
    brief = EditorialBrief(project_name="Culture", max_age_hours=24)
    assert _preflight_rejection(_article(published_at=None), brief) is None


def test_preflight_rejects_far_future_publication_date() -> None:
    now = datetime(2026, 11, 16, 12, tzinfo=UTC)
    published = (now + timedelta(hours=7)).isoformat()
    brief = EditorialBrief(project_name="Culture")
    reason = _preflight_rejection(_article(published_at=published), brief, now=now)
    assert reason == "Article publication date is more than 6 hours in the future."
