"""LeadHunter SERP worker package."""

from .searxng import SearchError, SearXNGClient

__all__ = ["SearchError", "SearXNGClient"]
