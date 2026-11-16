"""News source collection and normalization."""

from news_digest.collection.rss import RSSCollector, RSSSource
from news_digest.collection.normalization import NormalizedArticle, normalize_article, canonicalize_url

__all__ = [
    "RSSCollector",
    "RSSSource",
    "NormalizedArticle",
    "normalize_article",
    "canonicalize_url",
]
