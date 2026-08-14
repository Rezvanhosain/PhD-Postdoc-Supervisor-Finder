"""Environment / API-key detection for the proposal engine.

Keys (per this app's production policy):
    OPENALEX_API_KEY        required before any scholarly API call
    ANTHROPIC_API_KEY  or   required for drafting (Stage 4)
    OPENAI_API_KEY
    SEMANTIC_SCHOLAR_API_KEY  optional (fallback/enrichment)
    UNPAYWALL_EMAIL           optional (OA URL enrichment)
"""
from __future__ import annotations

import os

try:  # optional: load a local .env if python-dotenv is installed
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dotenv is an optional convenience
    pass
else:
    # A parse error in an existing .env must surface, not be swallowed.
    load_dotenv()

OPENALEX_HELP = (
    "OPENALEX_API_KEY is not set. OpenAlex offers basic keyless access, but this "
    "app requires a free key for reliable batch use, credit tracking, and "
    "production behaviour. Get one free at https://openalex.org/ (the 'premium'/"
    "API-key signup, no cost for the basic key) and set OPENALEX_API_KEY, e.g.:\n"
    '    setx OPENALEX_API_KEY "your-key"   (Windows, new shell)\n'
    '    export OPENALEX_API_KEY="your-key" (macOS/Linux)'
)

MODEL_KEY_HELP = (
    "No drafting model key found. Set ANTHROPIC_API_KEY (provider 'anthropic') or "
    "OPENAI_API_KEY (provider 'openai'/'openai-compatible') to enable Stage 4 "
    "drafting. Without it the engine can still run evidence-only mode."
)


def get(name: str) -> str | None:
    v = os.environ.get(name)
    return v.strip() if v and v.strip() else None


def openalex_key() -> str | None:
    return get("OPENALEX_API_KEY")


def has_openalex() -> bool:
    return openalex_key() is not None


def model_key(provider: str) -> str | None:
    if provider == "anthropic":
        return get("ANTHROPIC_API_KEY")
    # openai and openai-compatible both use OPENAI_API_KEY
    return get("OPENAI_API_KEY")


def has_model(provider: str) -> bool:
    return model_key(provider) is not None


def semantic_scholar_key() -> str | None:
    return get("SEMANTIC_SCHOLAR_API_KEY")


def unpaywall_email() -> str | None:
    return get("UNPAYWALL_EMAIL")
