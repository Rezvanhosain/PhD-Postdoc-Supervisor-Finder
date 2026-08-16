"""Tests for the local desktop app (usability layer). No live API calls: only
the pure helpers and the HTTP surface that does not touch the pipeline are
exercised. Generation itself is never triggered here."""
import inspect

import pytest
from fastapi.testclient import TestClient

from desktop_app import jobs, launch, server  # test: app imports
from proposal_engine.config import load_config
from proposal_engine.topics import load_topics


@pytest.fixture
def client():
    return TestClient(server.app)


def test_modules_import():
    assert hasattr(server, "app")
    assert callable(launch.main)
    assert callable(jobs.start_job)


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Proposal Engine" in r.text


def test_parse_topic_lines_and_write_topics_file(tmp_path):
    topics = jobs.parse_topic_lines("Federated learning in health\ngov | AI governance\n\n")
    assert [t["id"] for t in topics] == ["federated-learning-in-health", "gov"]
    assert topics[1]["title"] == "AI governance"
    out = jobs.write_topics_file(topics, tmp_path / "_ui_topics.yaml")
    assert out.is_file()
    # the temp file must load through the engine's own loader
    tl = load_topics(out)
    assert [t.id for t in tl.topics] == ["federated-learning-in-health", "gov"]


def test_resolve_config_file_creates_default_temp(tmp_path):
    dest = jobs.resolve_config_file(None, tmp_path)   # no path -> writes a temp config
    assert dest.is_file()
    cfg = load_config(dest)                            # must be a valid config
    assert cfg.renderer in ("rich_docx", "pandoc")


def test_resolve_config_file_uses_given_path(tmp_path):
    given = tmp_path / "my.yaml"
    given.write_text("model_provider: openai\nmodel_name: gpt-x\n", encoding="utf-8")
    assert jobs.resolve_config_file(str(given), tmp_path) == given


def test_start_job_with_no_topics_is_safe_error():
    # Empty input must NOT spawn a worker or call any API — just a clean error job.
    job_id = jobs.start_job(topics_raw="   \n  ", config_path=None, out_dir=None,
                            cv_path=None)
    job = jobs.get_job(job_id)
    assert job.status == "error"
    assert "topic" in job.message.lower()


def test_stop_endpoint_is_shell_free_and_clean(client):
    # The stop handler must not run OS commands / kill unrelated processes.
    src = inspect.getsource(server.stop).lower()
    for danger in ("subprocess", "os.system", "popen", "taskkill", "os.kill"):
        assert danger not in src

    class FakeServer:
        should_exit = False

    fake = FakeServer()
    server.app.state.server = fake
    try:
        r = client.post("/api/stop")
        assert r.status_code == 200
        assert r.json()["stopping"] is True
        assert fake.should_exit is True                    # asked to exit cleanly
        assert server.app.state.stop_requested is True
    finally:
        server.app.state.server = None
        server.app.state.stop_requested = False


def test_stop_endpoint_without_server_does_not_crash(client):
    server.app.state.server = None
    r = client.post("/api/stop")
    assert r.status_code == 200 and r.json()["stopping"] is True
    server.app.state.stop_requested = False


# --- profile-review gate is surfaced to the UI, not a file-only workflow ---- #
_WARN_CV = ("ARSALAN JAVED\nMaster of Science in Computer Science, CECOS "
            "University. Worked as Assistant Director at NADRA. Skills: Python, SQL.")
_WRONG = ("JOHN SMITH\nMaster of Science in Computer Science, Example University. "
          "Worked as a Software Engineer. Skills include Java and C++ development "
          "with database administration across large public information systems.")


def test_precheck_endpoint_reports_warning_field_and_choice(client, tmp_path):
    cv = tmp_path / "cv.txt"; cv.write_text(_WARN_CV, encoding="utf-8")
    r = client.post("/api/precheck", data={"cv_path": str(cv), "applicant_name": ""})
    assert r.status_code == 200
    g = r.json()
    assert g["provided"] is True and g["severity"] == "warning"
    f = g["flags"][0]
    # what was flagged, which field, and what proceeding does — all present
    assert f["code"] == "too_short" and f["field"] and f["consequence"]
    assert g["default_mode"] in ("safe_facts", "none")
    assert g["allow_override_without_personalization"] is True


def test_precheck_endpoint_flags_identity_conflict_as_data_block(client, tmp_path):
    cv = tmp_path / "cv.txt"; cv.write_text(_WRONG, encoding="utf-8")
    r = client.post("/api/precheck",
                    data={"cv_path": str(cv), "applicant_name": "Arsalan Javed"})
    g = r.json()
    assert g["severity"] == "critical" and g["blocking_class"] == "data"
    assert any(f["code"] == "identity_conflict" for f in g["flags"])
    assert g["allow_override_without_personalization"] is True   # override -> none allowed


def test_precheck_corrupt_file_is_file_block_without_override(client, tmp_path):
    cv = tmp_path / "cv.txt"; cv.write_text("�" * 300, encoding="utf-8")
    r = client.post("/api/precheck", data={"cv_path": str(cv)})
    g = r.json()
    assert g["blocking_class"] == "file"
    assert g["allow_override_without_personalization"] is False  # cannot override a corrupt file


def test_precheck_no_cv_is_ok(client):
    r = client.post("/api/precheck", data={"cv_path": ""})
    g = r.json()
    assert g["provided"] is False and g["severity"] == "ok"


def test_topicstatus_and_start_job_expose_profile_fields():
    # UI status object carries the profile-review surface fields.
    ts = jobs.TopicStatus(id="001", title="T")
    for attr in ("personalization", "profile_severity", "profile_flags",
                 "profile_default_mode", "profile_allow_override"):
        assert hasattr(ts, attr)
    # start_job accepts the new controls without triggering generation on bad input.
    import inspect
    sig = inspect.signature(jobs.start_job).parameters
    assert "profile_mode" in sig and "applicant_name" in sig
