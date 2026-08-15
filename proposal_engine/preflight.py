"""Stage 0 — Preflight environment checks."""
from __future__ import annotations

from . import env
from .config import EngineConfig
from .render import find_pandoc, pdf_engine


def run_preflight(config: EngineConfig) -> dict:
    model = env.has_model(config.model_provider)
    results = {
        "openalex_key": env.has_openalex(),
        "model_key": model,
        "model_provider": config.model_provider,
        "semantic_scholar_key": env.semantic_scholar_key() is not None,
        "unpaywall_email": env.unpaywall_email() is not None,
        "pandoc": find_pandoc() is not None,
        "pdf_engine": pdf_engine(),
        "evidence_only": (not model),
    }
    results["can_run"] = results["openalex_key"]
    return results


def preflight_messages(results: dict) -> list[str]:
    msgs: list[str] = []
    if not results["openalex_key"]:
        msgs.append(env.OPENALEX_HELP)
    if not results["model_key"]:
        msgs.append(env.MODEL_KEY_HELP + " Running in EVIDENCE-ONLY mode.")
    if not results["pandoc"]:
        from .render import PANDOC_INSTALL_HINT

        msgs.append(PANDOC_INSTALL_HINT)
    if not results["pdf_engine"]:
        msgs.append("No PDF engine (LibreOffice/Word) detected — PDF rendering will "
                    "fail visibly for affected topics.")
    return msgs
