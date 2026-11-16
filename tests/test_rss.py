"""Tests for RSS entry mapping and public-host validation."""

from email.utils import parsedate_to_datetime

import pytest

from news_digest.collection.rss import _entry_to_article, _published_at, _validate_public_url


def test_entry_maps_title_link_date_and_image() -> None:
    entry = {
        "title": "Example headline",
        "link": "https://example.com/news?utm_medium=rss",
        "summary": "<p>Short summary</p>",
        "published_parsed": (2026, 11, 16, 8, 30, 0, 0, 320, 0),
        "media_thumbnail": [{"url": "https://example.com/image.jpg"}],
    }
    article = _entry_to_article(entry)
    assert article is not None
    assert article.canonical_url == "https://example.com/news"
    assert article.title == "Example headline"
    assert article.published_at is not None
    assert article.image_url == "https://example.com/image.jpg"


@pytest.mark.asyncio
async def test_localhost_feed_is_rejected() -> None:
    with pytest.raises(ValueError, match="Private and local"):
        await _validate_public_url("http://localhost/feed.xml")


@pytest.mark.asyncio
async def test_literal_private_ip_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-public"):
        await _validate_public_url("http://127.0.0.1/feed.xml")
