"""KontentFabrik integration and management handlers."""

from news_digest.integrations.kontentfabrik.adapter import (
    KontentFabrikAdapter,
    KontentFabrikBinding,
    KontentFabrikError,
)
from news_digest.integrations.kontentfabrik.service import KontentFabrikProjectService
from news_digest.integrations.kontentfabrik.telegram import build_handlers

__all__ = [
    "KontentFabrikAdapter",
    "KontentFabrikBinding",
    "KontentFabrikError",
    "KontentFabrikProjectService",
    "build_handlers",
]
