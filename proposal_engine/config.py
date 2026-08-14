"""Configuration models for the proposal engine (Phase 0).

Everything the engine needs is described by ``config.yaml`` and validated with
Pydantic v2. This module is intentionally self-contained and does NOT import
from the legacy ``app`` package.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

# The default proposal section structure. Each section has a stable ``key``
# (used for artifact bookkeeping and [@key]-free bookkeeping), a human ``name``
# used as the DOCX heading, and a soft ``words`` floor used during drafting.
DEFAULT_SECTIONS: list[dict] = [
    {"key": "title", "name": "Title", "words": 12},
    {"key": "abstract", "name": "Abstract", "words": 180},
    {"key": "background", "name": "Background and Rationale", "words": 350},
    {"key": "problem_statement", "name": "Problem Statement", "words": 180},
    {"key": "research_gap", "name": "Evidence-Supported Research Gap", "words": 250},
    {"key": "aim", "name": "Aim", "words": 80},
    {"key": "objectives", "name": "Objectives", "words": 150},
    {"key": "questions", "name": "Research Questions and Hypotheses", "words": 150},
    {"key": "literature_review", "name": "Focused Literature Review", "words": 450},
    {"key": "framework", "name": "Conceptual or Theoretical Framework", "words": 220},
    {"key": "methodology", "name": "Methodology", "words": 400},
    {"key": "data_sources", "name": "Data Sources and Access Assumptions", "words": 200},
    {"key": "sampling", "name": "Sampling, Experimental, or Case-Selection Strategy", "words": 200},
    {"key": "analysis_plan", "name": "Analysis Plan", "words": 250},
    {"key": "ethics", "name": "Ethics", "words": 180},
    {"key": "limitations", "name": "Limitations and Risks", "words": 200},
    {"key": "contributions", "name": "Expected Academic and Practical Contributions", "words": 200},
    {"key": "feasibility", "name": "Feasibility", "words": 150},
    {"key": "timeline", "name": "Timeline and Work Plan", "words": 200},
    {"key": "references", "name": "References", "words": 0},
]


class SectionSpec(BaseModel):
    key: str
    name: str
    words: int = 150

    @field_validator("key")
    @classmethod
    def _key_ok(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("section key must be non-empty")
        return v.strip()


class EngineConfig(BaseModel):
    """Validated ``config.yaml``."""

    model_provider: str = Field(default="anthropic")
    model_name: str = Field(default="claude-sonnet-4-5")
    proposal_type: str = Field(default="PhD research proposal")
    discipline: str = Field(default="")
    target_country: str | None = None
    target_university: str | None = None
    length: str = Field(default="standard")
    citation_style: str = Field(default="apa")
    project_duration: str = Field(default="36 months")
    evidence_minimum: int = Field(default=12, ge=1)

    # DOCX render path. 'rich_docx' (default) is the template-matching python-docx
    # builder — it produces the metadata first page, numbered blue headings, Times
    # New Roman body, teal Gantt work-plan table, and the Page X of Y footer.
    # Pandoc renders only the Markdown and cannot reproduce those, so it is used
    # ONLY when explicitly requested with 'pandoc' (and never auto-selected just
    # because Pandoc happens to be installed).
    renderer: str = Field(default="rich_docx")

    # Optional proposal metadata for the template's first page. Any field left
    # unset is omitted cleanly from the document (never a placeholder).
    applicant_name: str | None = None
    proposed_programme: str | None = None
    target_supervisor: str | None = None
    university: str | None = None
    proposal_date: str | None = None
    proposal_title: str | None = None

    # Optional knobs (sensible defaults keep config.yaml short).
    model_base_url: str | None = None
    max_broaden_attempts: int = Field(default=1, ge=0)
    per_query_results: int = Field(default=25, ge=1)
    sections: list[SectionSpec] = Field(default_factory=lambda: [SectionSpec(**s) for s in DEFAULT_SECTIONS])

    @field_validator("model_provider")
    @classmethod
    def _provider_ok(cls, v: str) -> str:
        allowed = {"anthropic", "openai", "openai-compatible"}
        if v not in allowed:
            raise ValueError(f"model_provider must be one of {sorted(allowed)}, got {v!r}")
        return v

    @field_validator("citation_style")
    @classmethod
    def _style_ok(cls, v: str) -> str:
        return v.strip().lower() or "apa"

    @field_validator("renderer")
    @classmethod
    def _renderer_ok(cls, v: str) -> str:
        v = (v or "").strip().lower()
        allowed = {"rich_docx", "pandoc"}
        if v not in allowed:
            raise ValueError(f"renderer must be one of {sorted(allowed)}, got {v!r}")
        return v

    @property
    def target(self) -> str:
        return self.target_university or self.target_country or ""

    @property
    def metadata(self) -> dict:
        """First-page metadata for the renderer (only set fields are included)."""
        fields = {
            "applicant_name": self.applicant_name,
            "proposed_programme": self.proposed_programme,
            "target_supervisor": self.target_supervisor,
            "university": self.university or self.target_university,
            "proposal_date": self.proposal_date,
            "proposal_title": self.proposal_title,
            "top_label": self.proposal_type,
        }
        return {k: v for k, v in fields.items() if v}


def load_config(path: str | Path) -> EngineConfig:
    """Load and validate ``config.yaml``. Raises on malformed input."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"config file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("config.yaml must be a mapping at the top level")
    return EngineConfig(**raw)
