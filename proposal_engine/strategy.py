"""Stage 2 — Search Strategy.

With a model key: the LLM proposes >=3 queries + inclusion/exclusion criteria
as schema-valid JSON. Without a model key: deterministic keyword-template
queries. Gate: at least 3 usable queries.
"""
from __future__ import annotations

from pathlib import Path

from .config import EngineConfig
from .llm import LLMError
from .topics import Topic

_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "for", "and", "or", "to", "with", "using",
    "based", "via", "study", "analysis", "approach", "towards", "toward", "into",
    "from", "by", "at", "as", "is", "are", "how", "what", "role", "impact",
}

MIN_QUERIES = 3


def _key_terms(topic: Topic) -> list[str]:
    if topic.keywords:
        return [k.strip() for k in topic.keywords if k.strip()]
    words = [w.strip(",.;:()[]").lower() for w in topic.title.split()]
    terms = [w for w in words if w and w not in _STOPWORDS and len(w) > 2]
    # preserve order, de-dup
    seen: list[str] = []
    for t in terms:
        if t not in seen:
            seen.append(t)
    return seen


def deterministic_strategy(topic: Topic, config: EngineConfig) -> dict:
    terms = _key_terms(topic)
    queries: list[str] = [topic.title.strip()]
    if terms:
        queries.append(" ".join(terms[:4]))
        queries.append(" ".join(terms[:2]) + " review")
        queries.append(" ".join(terms[:3]) + " methodology")
    if config.discipline:
        queries.append(f"{topic.title.strip()} {config.discipline}")
    # de-duplicate while preserving order
    uniq: list[str] = []
    for q in queries:
        q = q.strip()
        if q and q.lower() not in {u.lower() for u in uniq}:
            uniq.append(q)
    year_from = 2015
    return {
        "mode": "deterministic",
        "queries": uniq,
        "inclusion_criteria": [
            "Peer-reviewed journal articles or conference papers",
            f"Published from {year_from} onward (older seminal work admitted if highly cited)",
            "Written in English",
            f"Topically relevant to: {', '.join(terms[:5]) or topic.title}",
            "Record has a retrievable abstract",
        ],
        "exclusion_criteria": [
            "Editorials, opinion pieces, and non-peer-reviewed preprints without metrics",
            "Records without an abstract or resolvable identifier",
        ],
    }


_SCHEMA_HINT = (
    'Return ONLY JSON with this shape: '
    '{"queries": ["...", "...", "..."], '
    '"inclusion_criteria": ["..."], "exclusion_criteria": ["..."]}. '
    "Provide at least 3 distinct, specific search queries suitable for a "
    "scholarly database (OpenAlex/Semantic Scholar)."
)


def llm_strategy(topic: Topic, config: EngineConfig, llm) -> dict:
    system = ("You are a research librarian designing a literature search "
              f"strategy for a {config.proposal_type} in {config.discipline or 'the stated field'}. "
              + _SCHEMA_HINT)
    user = (f"Topic id: {topic.id}\nTitle: {topic.title}\n"
            f"Description: {topic.description or '(none)'}\n"
            f"Seed keywords: {', '.join(topic.keywords) or '(none)'}\n"
            f"Target: {config.target or '(unspecified)'}")
    data = llm.generate_json(system, user, max_tokens=800)
    queries = [q.strip() for q in (data.get("queries") or []) if isinstance(q, str) and q.strip()]
    if len(queries) < MIN_QUERIES:
        raise LLMError(f"strategy returned only {len(queries)} queries (need >= {MIN_QUERIES})")
    return {
        "mode": "llm",
        "queries": queries,
        "inclusion_criteria": [c for c in (data.get("inclusion_criteria") or []) if c],
        "exclusion_criteria": [c for c in (data.get("exclusion_criteria") or []) if c],
    }


def build_strategy(topic: Topic, config: EngineConfig, llm=None) -> dict:
    """Choose LLM or deterministic strategy and enforce the query gate."""
    if llm is not None:
        strat = llm_strategy(topic, config, llm)
    else:
        strat = deterministic_strategy(topic, config)
    if len(strat["queries"]) < MIN_QUERIES:
        # deterministic fallback should always satisfy this; guard anyway
        raise ValueError(f"search strategy has < {MIN_QUERIES} usable queries")
    return strat


def render_strategy_md(topic: Topic, strat: dict) -> str:
    lines = [f"# Search Strategy — {topic.title}", "",
             f"*Mode:* {strat['mode']}", "", "## Queries"]
    for i, q in enumerate(strat["queries"], 1):
        lines.append(f"{i}. `{q}`")
    lines += ["", "## Inclusion Criteria"]
    lines += [f"- {c}" for c in strat.get("inclusion_criteria", [])] or ["- (none)"]
    lines += ["", "## Exclusion Criteria"]
    lines += [f"- {c}" for c in strat.get("exclusion_criteria", [])] or ["- (none)"]
    return "\n".join(lines) + "\n"


def write_strategy(topic: Topic, strat: dict, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_strategy_md(topic, strat), encoding="utf-8")
    return out
