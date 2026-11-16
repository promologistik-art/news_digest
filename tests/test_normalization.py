"""Tests for canonical article normalization."""

import pytest

from news_digest.collection.normalization import canonicalize_url, normalize_article


def test_canonical_url_removes_tracking_and_fragment() -> None:
    assert canonicalize_url(
        "HTTPS://Example.com/story?utm_source=feed&id=7#section"
    ) == "https://example.com/story?id=7"


def test_normalize_html_and_whitespace() -> None:
    article = normalize_article(
        url="https://example.com/a",
        title="  <b>News</b>   item ",
        description="<p>Hello&nbsp; world</p>",
        content="<div>Full <em>text</em></div>",
    )
    assert article.title == "News item"
    assert article.description == "Hello world"
    assert article.content == "Full text"
    assert len(article.content_hash) == 64


def test_invalid_article_url_is_rejected() -> None:
    with pytest.raises(ValueError):
        canonicalize_url("file:///etc/passwd")


def test_title_is_required() -> None:
    with pytest.raises(ValueError, match="title"):
        normalize_article(url="https://example.com/a", title="  ")
