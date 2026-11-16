"""News source collection and normalization."""

from news_digest.collection.normalization import (
    NormalizedArticle,
    canonicalize_url,
    normalize_article,
)
from news_digest.collection.rss import RSSCollector, RSSSource

__all__ = [
    "NormalizedArticle",
    "RSSCollector",
    "RSSSource",
    "canonicalize_url",
    "normalize_article",
]
