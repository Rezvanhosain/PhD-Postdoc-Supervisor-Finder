import pytest
from pydantic import ValidationError

from proposal_engine.config import EngineConfig, load_config
from proposal_engine.topics import TopicList, load_topics, slugify


def test_config_defaults_and_sections():
    c = EngineConfig()
    assert c.evidence_minimum == 12
    assert len(c.sections) == 20
    assert c.sections[0].key == "title"


def test_config_rejects_bad_provider():
    with pytest.raises(ValidationError):
        EngineConfig(model_provider="mistral")


def test_renderer_defaults_to_rich_docx():
    assert EngineConfig().renderer == "rich_docx"


def test_renderer_accepts_pandoc_and_rejects_other():
    assert EngineConfig(renderer="pandoc").renderer == "pandoc"
    with pytest.raises(ValidationError):
        EngineConfig(renderer="latex")


def test_config_target_prefers_university():
    c = EngineConfig(target_country="Germany", target_university="TU Munich")
    assert c.target == "TU Munich"


def test_load_config_roundtrip(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("model_provider: openai\nmodel_name: gpt-x\nevidence_minimum: 8\n",
                 encoding="utf-8")
    c = load_config(p)
    assert c.model_provider == "openai" and c.evidence_minimum == 8


def test_topics_reject_duplicate_ids():
    with pytest.raises(ValidationError):
        TopicList(topics=[{"id": "t1", "title": "A"}, {"id": "t1", "title": "B"}])


def test_topics_reject_empty():
    with pytest.raises(ValidationError):
        TopicList(topics=[])


def test_load_topics_bare_list(tmp_path):
    p = tmp_path / "topics.yaml"
    p.write_text("- id: t1\n  title: My Topic\n", encoding="utf-8")
    tl = load_topics(p)
    assert tl.topics[0].id == "t1"
    assert slugify("Hello World!") == "hello-world"
