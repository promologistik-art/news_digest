from __future__ import annotations

import pytest
from pydantic import ValidationError

from news_digest.editorial.models import EditorialAssessment, EditorialBrief, EditorialDraft
from news_digest.editorial.service import EditorialError, _parse_model


def test_editorial_brief_rejects_invalid_significance_threshold() -> None:
    with pytest.raises(ValidationError):
        EditorialBrief(project_name="Culture", min_significance=101)


def test_assessment_scores_are_bounded() -> None:
    with pytest.raises(ValidationError):
        EditorialAssessment(
            relevant=True,
            topic="books",
            relevance_score=120,
            significance_score=80,
            novelty_score=50,
            confidence=90,
        )


def test_parse_model_accepts_json_fenced_response() -> None:
    fenced = chr(96) * 3
    response = (
        fenced + "json\n"
        + '{"headline":"Заголовок","caption":"Текст",'
        + '"source_url":"https://example.com/story"}\n'
        + fenced
    )
    result = _parse_model(EditorialDraft, response)
    assert result.headline == "Заголовок"
    assert str(result.source_url) == "https://example.com/story"


def test_parse_model_rejects_non_json() -> None:
    with pytest.raises(EditorialError):
        _parse_model(EditorialAssessment, "not json")
