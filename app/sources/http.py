"""Polite HTTP client shared by all sources: rate limiting per host,
on-disk caching, robots.txt checking, and error logging."""
from __future__ import annotations

import hashlib
import json
import time
import urllib.robotparser
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.config import CACHE_DIR, get_setting
from app.db import log_error
from app.logging_setup import log

MIN_INTERVAL = 1.5  # seconds between requests to the same host
CACHE_TTL = 60 * 60 * 24  # 24h

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


def _ua() -> str:
    contact = get_setting("CONTACT_EMAIL") or "anonymous"
    return f"PhD-Postdoc-Supervisor-Finder/0.1 (personal research tool; mailto:{contact})"


def robots_allowed(url: str) -> bool:
    host = urlparse(url).netloc
    rp = _robots.get(host)
    if rp is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            resp = httpx.get(f"https://{host}/robots.txt", timeout=10,
                             headers={"User-Agent": _ua()}, follow_redirects=True)
            rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
        except Exception:
            rp.parse([])  # unknown -> permissive but rate-limited
        _robots[host] = rp
    return rp.can_fetch(_ua(), url)


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    wait = _last_hit.get(host, 0) + MIN_INTERVAL - time.time()
    if wait > 0:
        time.sleep(wait)
    _last_hit[host] = time.time()


def _cache_path(url: str, params: Optional[dict]) -> Path:
    key = hashlib.sha256((url + json.dumps(params or {}, sort_keys=True)).encode()).hexdigest()
    return CACHE_DIR / f"{key}.json"


def get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None,
        use_cache: bool = True, check_robots: bool = False) -> Optional[str]:
    """GET with caching + throttling. Returns body text or None on failure."""
    cp = _cache_path(url, params)
    if use_cache and cp.exists() and time.time() - cp.stat().st_mtime < CACHE_TTL:
        return cp.read_text(encoding="utf-8")
    if check_robots and not robots_allowed(url):
        log_error("scrape", f"robots.txt disallows {url}", needs_review=True)
        return None
    _throttle(url)
    try:
        h = {"User-Agent": _ua()}
        if headers:
            h.update(headers)
        resp = httpx.get(url, params=params, headers=h, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        cp.write_text(resp.text, encoding="utf-8")
        return resp.text
    except Exception as e:
        log.warning("GET failed %s: %s", url, e)
        log_error("scrape" if check_robots else "api", f"GET failed: {url}", str(e),
                  needs_review=check_robots)
        return None


def get_json(url: str, params: Optional[dict] = None,
             headers: Optional[dict] = None, use_cache: bool = True) -> Optional[Any]:
    body = get(url, params, headers, use_cache)
    if body is None:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        log_error("api", f"Bad JSON from {url}", str(e))
        return None
