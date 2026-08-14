"""Provider-agnostic LLM client (anthropic | openai | openai-compatible).

Talks to the HTTP APIs directly via httpx so no vendor SDK is required.
Callers use ``generate_json`` and always receive parsed JSON or a raised
error — there are no silent fallbacks.
"""
from __future__ import annotations

import json
import re
import time

import httpx


class LLMError(RuntimeError):
    pass


# Transient HTTP statuses worth a bounded retry (rate limit / server errors).
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_TRANSIENT = 2          # extra attempts for transient errors/exceptions
_BACKOFF_BASE = 0.5         # seconds; multiplied by the attempt number


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str):
    """Parse a JSON object/array from a model response, tolerating code fences
    and surrounding prose."""
    if text is None:
        raise LLMError("empty model response")
    cleaned = _FENCE_RE.sub("", text).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fall back to the first balanced {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"could not parse JSON from model response: {text[:200]!r}")


class LLMClient:
    def __init__(self, provider: str, model: str, api_key: str,
                 base_url: str | None = None, timeout: float = 120.0,
                 key_provider=None):
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = timeout
        # Optional callable returning a fresh key from the current environment.
        # On a 401 the client rebuilds its credential from this and retries once.
        self._key_provider = key_provider

    def generate(self, system: str, user: str, max_tokens: int = 2000) -> str:
        if self.provider == "anthropic":
            return self._anthropic(system, user, max_tokens)
        return self._openai(system, user, max_tokens)

    def generate_json(self, system: str, user: str, max_tokens: int = 2000):
        return parse_json(self.generate(system, user, max_tokens))

    # ---- shared request path (retries; never logs the key) -----------
    def _refresh_key(self) -> bool:
        """Reload the API key from the current environment. Returns True when a
        (re)load happened, so the caller may retry the 401 exactly once."""
        if not self._key_provider:
            return False
        try:
            fresh = self._key_provider()
        except Exception:
            return False
        if fresh:
            self.api_key = fresh
            return True
        return False

    @staticmethod
    def _sanitize_error(resp: httpx.Response) -> str:
        """Provider error message + request id, with NO credential material."""
        rid = (resp.headers.get("x-request-id")
               or resp.headers.get("X-Request-Id")
               or resp.headers.get("cf-ray") or "")
        message, code = "", ""
        try:
            body = resp.json()
            err = body.get("error") if isinstance(body, dict) else None
            if isinstance(err, dict):
                message = err.get("message") or ""
                code = err.get("code") or err.get("type") or ""
            elif isinstance(err, str):
                message = err
        except Exception:
            message = ""
        parts = [f"HTTP {resp.status_code}"]
        if code:
            parts.append(f"code={code}")
        if message:
            parts.append(message)
        out = "; ".join(parts)
        if rid:
            out += f" [request-id: {rid}]"
        return out

    def _request(self, url: str, headers_fn, payload: dict) -> dict:
        """POST with bounded retries. 401 -> rebuild key from env and retry once;
        429/5xx/timeouts/connection errors -> bounded retries with backoff."""
        transient_left = _MAX_TRANSIENT
        refreshed = False
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = httpx.post(url, timeout=self.timeout,
                                  headers=headers_fn(), json=payload)
            except httpx.RequestError as e:  # timeout / connection / transport
                if transient_left > 0:
                    transient_left -= 1
                    time.sleep(_BACKOFF_BASE * attempt)
                    continue
                raise LLMError(
                    f"{self.provider} request failed after retries: "
                    f"{type(e).__name__}") from e
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code == 401 and not refreshed and self._refresh_key():
                refreshed = True          # exactly one rebuild-and-retry
                continue
            if resp.status_code in _RETRY_STATUS and transient_left > 0:
                transient_left -= 1
                time.sleep(_BACKOFF_BASE * attempt)
                continue
            raise LLMError(f"{self.provider} error: {self._sanitize_error(resp)}")

    # ---- providers ---------------------------------------------------
    def _anthropic(self, system: str, user: str, max_tokens: int) -> str:
        base = (self.base_url or "https://api.anthropic.com").rstrip("/")
        data = self._request(
            f"{base}/v1/messages",
            lambda: {"x-api-key": self.api_key,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            {"model": self.model, "max_tokens": max_tokens, "system": system,
             "messages": [{"role": "user", "content": user}]},
        )
        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
        if not text:
            raise LLMError("anthropic returned no text content")
        return text

    def _openai(self, system: str, user: str, max_tokens: int) -> str:
        base = (self.base_url or "https://api.openai.com/v1").rstrip("/")
        data = self._request(
            f"{base}/chat/completions",
            lambda: {"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"},
            {"model": self.model, "max_tokens": max_tokens,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}]},
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected openai response shape: {e}") from e
