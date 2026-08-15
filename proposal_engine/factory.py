"""Build live pipeline dependencies (provider, LLM, DOI verifier) from config+env."""
from __future__ import annotations

from pathlib import Path

from . import env
from .config import EngineConfig
from .evidence import LiveProvider
from .llm import LLMClient
from .sources import HttpClient
from .sources import crossref


def build_http_client(cache_dir: Path) -> HttpClient:
    contact = env.unpaywall_email() or env.get("CONTACT_EMAIL") or ""
    return HttpClient(cache_dir=cache_dir, contact=contact)


def build_provider(client: HttpClient) -> LiveProvider:
    key = env.openalex_key()
    if not key:
        raise RuntimeError("OPENALEX_API_KEY missing; cannot build live provider")
    return LiveProvider(client, key, env.semantic_scholar_key(), env.unpaywall_email())


def _reload_key(provider: str) -> str | None:
    """Re-read the model key from the authoritative .env (override=True), so a
    stale key that leaked into the process environment cannot mask it. Used by
    the LLM client to rebuild its credential and retry exactly once on a 401."""
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except ImportError:
        pass
    return env.model_key(provider)


def build_llm(config: EngineConfig) -> LLMClient | None:
    key = env.model_key(config.model_provider)
    if not key:
        return None
    # key_provider lets the client rebuild the key from the reloaded .env and
    # retry exactly once on a 401 (never logs the key).
    return LLMClient(config.model_provider, config.model_name, key,
                     base_url=config.model_base_url,
                     key_provider=lambda: _reload_key(config.model_provider))


def build_verify_doi(client: HttpClient):
    return lambda doi: crossref.lookup_doi(client, doi)
