"""Canonical URL, text and content-hash normalization."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "mc_cid",
    "mc_eid",
    "ref_src",
}
_TRACKING_PREFIXES = ("utm_",)
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizedArticle:
    canonical_url: str
    title: str
    description: str
    content: str
    published_at: str | None
    image_url: str | None
    content_hash: str


def canonicalize_url(url: str) -> str:
    """Remove fragments and common tracking parameters without changing article identity."""
    value = url.strip()
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("Article URL must be an absolute HTTP(S) URL.")
    if parts.username or parts.password:
        raise ValueError("Credentials are not allowed in article URLs.")
    port = parts.port
    netloc = host
    if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = f"{host}:{port}"
    query = [
        (key, item)
        for key, item in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_KEYS
        and not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    query.sort()
    path = parts.path or "/"
    return urlunsplit((scheme, netloc, path, urlencode(query, doseq=True), ""))


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", text).strip()


def content_fingerprint(title: str, description: str, content: str) -> str:
    normalized = "\n".join(
        _WHITESPACE.sub(" ", item).strip().casefold()
        for item in (title, description, content)
        if item
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_article(
    *,
    url: str,
    title: str,
    description: str | None = None,
    content: str | None = None,
    published_at: str | None = None,
    image_url: str | None = None,
) -> NormalizedArticle:
    clean_title = clean_text(title)
    if not clean_title:
        raise ValueError("Article title is required.")
    clean_description = clean_text(description)
    clean_content = clean_text(content)
    canonical = canonicalize_url(url)
    clean_image = canonicalize_url(image_url) if image_url else None
    return NormalizedArticle(
        canonical_url=canonical,
        title=clean_title,
        description=clean_description,
        content=clean_content,
        published_at=published_at,
        image_url=clean_image,
        content_hash=content_fingerprint(clean_title, clean_description, clean_content),
    )
