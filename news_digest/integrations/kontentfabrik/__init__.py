"""Read-only identity integration with KontentFabrik."""

from news_digest.integrations.kontentfabrik.adapter import KontentFabrikAdapter
from news_digest.integrations.kontentfabrik.service import KontentFabrikProjectService

__all__ = ["KontentFabrikAdapter", "KontentFabrikProjectService"]
