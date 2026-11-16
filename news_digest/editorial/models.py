"""Validated data contracts for project-specific news editing."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class EditorialBrief(BaseModel):
    """Editorial policy belonging to one news project."""

    model_config = ConfigDict(extra="forbid")

    project_name: str = Field(min_length=1, max_length=160)
    language: str = "ru"
    topics: list[str] = Field(default_factory=list)
    geographies: list[str] = Field(default_factory=list)
    audience: str = ""
    style_guide: str = "Пиши ясно, содержательно и без рекламных клише."
    excluded_topics: list[str] = Field(default_factory=list)
    min_significance: int = Field(default=55, ge=0, le=100)
    max_age_hours: int = Field(default=72, ge=1, le=8760)
    monthly_ai_budget_rub: float | None = Field(default=None, ge=0)


class EditorialAssessment(BaseModel):
    """Structured relevance and significance assessment of a source article."""

    model_config = ConfigDict(extra="forbid")

    relevant: bool
    topic: str
    geography: str | None = None
    relevance_score: int = Field(ge=0, le=100)
    significance_score: int = Field(ge=0, le=100)
    novelty_score: int = Field(ge=0, le=100)
    confidence: int = Field(ge=0, le=100)
    article_date: str | None = None
    event_date: str | None = None
    factual_points: list[str] = Field(default_factory=list, max_length=12)
    uncertainties: list[str] = Field(default_factory=list, max_length=12)
    rejection_reason: str | None = None


class EditorialDraft(BaseModel):
    """Publication-ready copy constrained to facts from the supplied source."""

    model_config = ConfigDict(extra="forbid")

    headline: str = Field(min_length=1, max_length=180)
    caption: str = Field(min_length=1, max_length=900)
    source_url: HttpUrl
    factual_points_used: list[str] = Field(default_factory=list, max_length=12)
    caveat: str | None = None
