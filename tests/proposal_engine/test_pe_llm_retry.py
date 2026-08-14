"""LLM client reliability: 401 rebuild-and-retry-once, bounded transient retries,
sanitized errors that never leak the key. No network — httpx.post is faked.
"""
from __future__ import annotations

import pytest

from proposal_engine import llm


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body


OK_BODY = {"choices": [{"message": {"content": "OK"}}]}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda *a, **k: None)


def _install(monkeypatch, responses):
    """Feed a queue of FakeResp (or raised exceptions); record auth headers."""
    calls = {"n": 0, "auth": []}
    seq = list(responses)

    def fake_post(url, timeout=None, headers=None, json=None):
        calls["n"] += 1
        calls["auth"].append((headers or {}).get("Authorization", ""))
        item = seq.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    return calls


def test_401_rebuilds_key_from_env_and_retries_once(monkeypatch):
    calls = _install(monkeypatch, [
        FakeResp(401, {"error": {"message": "bad key", "code": "invalid_api_key"}},
                 {"x-request-id": "req_1"}),
        FakeResp(200, OK_BODY),
    ])
    client = llm.LLMClient("openai", "gpt-x", "BADKEY",
                           key_provider=lambda: "GOODKEY")
    assert client.generate("s", "u") == "OK"
    assert calls["n"] == 2                       # exactly one retry
    assert "Bearer GOODKEY" in calls["auth"][1]  # retried with the refreshed key


def test_persistent_401_raises_sanitized_error_without_key(monkeypatch):
    calls = _install(monkeypatch, [
        FakeResp(401, {"error": {"message": "no access", "code": "invalid_api_key"}},
                 {"x-request-id": "req_9"}),
        FakeResp(401, {"error": {"message": "no access", "code": "invalid_api_key"}},
                 {"x-request-id": "req_9"}),
    ])
    client = llm.LLMClient("openai", "gpt-x", "SECRETKEY",
                           key_provider=lambda: "SECRETKEY")
    with pytest.raises(llm.LLMError) as ei:
        client.generate("s", "u")
    msg = str(ei.value)
    assert "401" in msg and "req_9" in msg and "invalid_api_key" in msg
    assert "SECRETKEY" not in msg                 # never leaks the key
    assert calls["n"] == 2                         # initial + exactly one refresh retry


def test_401_without_key_provider_does_not_retry(monkeypatch):
    calls = _install(monkeypatch, [
        FakeResp(401, {"error": {"message": "bad", "code": "invalid_api_key"}},
                 {"x-request-id": "r"})])
    client = llm.LLMClient("openai", "gpt-x", "K")  # no key_provider
    with pytest.raises(llm.LLMError):
        client.generate("s", "u")
    assert calls["n"] == 1


def test_429_is_retried_then_succeeds(monkeypatch):
    calls = _install(monkeypatch, [
        FakeResp(429, {"error": {"message": "slow down"}}, {"x-request-id": "r"}),
        FakeResp(200, OK_BODY),
    ])
    client = llm.LLMClient("openai", "gpt-x", "K")
    assert client.generate("s", "u") == "OK"
    assert calls["n"] == 2


def test_factory_reload_key_reads_env_authoritatively(monkeypatch):
    import dotenv

    from proposal_engine import factory
    seen = {}
    monkeypatch.setattr(dotenv, "load_dotenv",
                        lambda *a, **k: seen.update(k) or True)
    monkeypatch.setattr(factory.env, "model_key", lambda provider: "RELOADED-KEY")
    assert factory._reload_key("openai") == "RELOADED-KEY"
    assert seen.get("override") is True  # .env wins over a stale process env var


def test_connection_errors_are_bounded_then_raise(monkeypatch):
    calls = _install(monkeypatch, [
        llm.httpx.ConnectError("boom"),
        llm.httpx.ConnectError("boom"),
        llm.httpx.ConnectError("boom"),
    ])
    client = llm.LLMClient("openai", "gpt-x", "K")
    with pytest.raises(llm.LLMError) as ei:
        client.generate("s", "u")
    assert "after retries" in str(ei.value)
    assert calls["n"] == 1 + llm._MAX_TRANSIENT   # initial + bounded retries
