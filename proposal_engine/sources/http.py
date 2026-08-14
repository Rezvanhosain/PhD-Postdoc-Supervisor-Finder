"""Thin, polite, cached HTTP client for the proposal engine.

Self-contained (no dependency on the legacy ``app`` package). Provides
per-host throttling and on-disk JSON caching so batch runs and tests stay
fast and reproducible.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

MIN_INTERVAL = 1.1  # seconds between requests to the same host
CACHE_TTL = 60 * 60 * 24 * 7  # 7 days


class HttpClient:
    def __init__(self, cache_dir: str | Path | None = None, contact: str = "",
                 timeout: float = 30.0):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.contact = contact or "anonymous"
        self.timeout = timeout
        self._last_hit: dict[str, float] = {}

    def _ua(self) -> str:
        return f"proposal-engine/0.1 (research tool; mailto:{self.contact})"

    def _cache_path(self, url: str, params: dict | None) -> Path | None:
        if not self.cache_dir:
            return None
        key = hashlib.sha256(
            (url + json.dumps(params or {}, sort_keys=True)).encode()
        ).hexdigest()
        return self.cache_dir / f"{key}.json"

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self._last_hit.get(host, 0.0) + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_hit[host] = time.time()

    def get_json(self, url: str, params: dict | None = None,
                 headers: dict | None = None, use_cache: bool = True) -> Any | None:
        cp = self._cache_path(url, params)
        if use_cache and cp and cp.exists() and time.time() - cp.stat().st_mtime < CACHE_TTL:
            try:
                return json.loads(cp.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        self._throttle(url)
        h = {"User-Agent": self._ua(), "Accept": "application/json"}
        if headers:
            h.update(headers)
        try:
            resp = httpx.get(url, params=params, headers=h, timeout=self.timeout,
                             follow_redirects=True)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            raise SourceError(f"GET {url} failed: {e}") from e
        if cp:
            try:
                cp.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
        return data


class SourceError(RuntimeError):
    """Raised when a scholarly source call fails in a way the caller must see."""
