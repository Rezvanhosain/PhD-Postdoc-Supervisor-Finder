"""Topic-list models and loader for ``topics.yaml``."""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    s = _SLUG_RE.sub("-", value.lower()).strip("-")
    return s or "topic"


class Topic(BaseModel):
    id: str
    title: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    client: str | None = None  # optional per-topic client/profile directory or file

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic id must be non-empty")
        return v

    @field_validator("title")
    @classmethod
    def _title_ok(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("topic title must be non-empty")
        return v

    @property
    def slug(self) -> str:
        return slugify(self.id)

    def query_seed(self) -> str:
        """Best free-text seed for search: title plus optional description."""
        return self.title if not self.description else f"{self.title}. {self.description}"


class TopicList(BaseModel):
    topics: list[Topic]

    @field_validator("topics")
    @classmethod
    def _non_empty_unique(cls, v: list[Topic]) -> list[Topic]:
        if not v:
            raise ValueError("topics.yaml must contain at least one topic")
        ids = [t.id for t in v]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate topic ids: {sorted(dupes)}")
        return v


def load_topics(path: str | Path) -> TopicList:
    """Load and validate ``topics.yaml``."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"topics file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if isinstance(raw, list):  # allow a bare list of topics
        raw = {"topics": raw}
    if not isinstance(raw, dict):
        raise ValueError("topics.yaml must be a mapping or a list")
    return TopicList(**raw)
