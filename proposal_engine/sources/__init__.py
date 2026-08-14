"""Self-contained scholarly source clients for the proposal engine."""
from .http import HttpClient, SourceError

__all__ = ["HttpClient", "SourceError"]
