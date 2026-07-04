"""Optional LLM assistance via any OpenAI-compatible API.

The app never depends on this: every generator has a deterministic
template fallback. The LLM is only used to *reword* content built from
verified facts — prompts explicitly forbid adding facts, citations, or
publications not present in the input."""
from __future__ import annotations

from typing import Optional

import httpx

from app.config import get_setting
from app.db import log_error

GUARD = ("STRICT RULES: Use ONLY facts provided in the input. Never invent degrees, "
         "publications, citations, DOIs, jobs, awards, skills, or claims about the "
         "supervisor. If information is missing, leave a [FILL IN] placeholder. "
         "Do not add any reference that is not in the provided verified list.")


def available() -> bool:
    return bool(get_setting("OPENAI_API_KEY"))


def complete(system: str, user: str, max_tokens: int = 2000) -> Optional[str]:
    """Returns the completion text, or None (caller falls back to templates)."""
    key = get_setting("OPENAI_API_KEY")
    if not key:
        return None
    base = (get_setting("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    model = get_setting("OPENAI_MODEL") or "gpt-4o-mini"
    try:
        resp = httpx.post(f"{base}/chat/completions", timeout=90,
                          headers={"Authorization": f"Bearer {key}"},
                          json={"model": model, "max_tokens": max_tokens,
                                "messages": [{"role": "system", "content": system + "\n" + GUARD},
                                             {"role": "user", "content": user}]})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        log_error("api", f"LLM call failed, using template fallback: {e}")
        return None
