"""Stage 4 — Draft.

Drafts the proposal section-by-section (one LLM call per section), validating
each section and retrying at most twice with the validator errors. Only runs
when a model key is available. No silent fallbacks.
"""
from __future__ import annotations

import re
from pathlib import Path

from .candidate_context import find_contamination
from .config import EngineConfig
from .llm import LLMError
from .topics import Topic
from .validators import validate_section

MAX_RETRIES = 2

# Sections that must carry at least one in-text citation.
CITATION_REQUIRED = {
    "background", "problem_statement", "research_gap", "literature_review",
    "framework", "methodology",
}
# Sections excluded from LLM drafting (built elsewhere / trivial).
SKIP_DRAFT = {"references"}


class DraftingFailed(RuntimeError):
    def __init__(self, section_key: str, errors: list[str]):
        self.section_key = section_key
        self.errors = errors
        super().__init__(f"drafting_validation_failed at '{section_key}': {errors}")


# Prefixes of the two validation errors that specifically indicate a *citation*
# problem (a hallucinated key, or a required section with no [@key]). Distinct
# from length, placeholder, resource-claim, or topic-fidelity contamination
# errors. Used only to decide whether a whole-topic redraft is worth one more
# attempt before failing closed — this does NOT change what validate_section
# rejects; citation validation is unchanged.
_CITATION_ERROR_PREFIXES = (
    "citation keys not in evidence_store",
    "no in-text citations",
)


def is_citation_failure(exc: "DraftingFailed") -> bool:
    """True iff a drafting failure is caused ONLY by citation-validation errors
    (every recorded error is a citation problem). Any non-citation error
    (word floor, placeholders, resource claims, candidate-direction contamination)
    returns False so the pipeline still fails closed immediately."""
    errs = getattr(exc, "errors", None) or []
    if not errs:
        return False
    return all(any(e.startswith(p) for p in _CITATION_ERROR_PREFIXES) for e in errs)


# Transient model-output errors: a malformed/truncated JSON draw (or any other
# LLMError surfaced while drafting a section, which draft_section records as
# "invalid JSON output: ..."). Like a citation-only miss, these are worth one
# more whole-topic draw rather than an immediate fail.
_TRANSIENT_ERROR_PREFIXES = (
    "invalid JSON output",
)


def is_retryable_draft_failure(exc: "DraftingFailed") -> bool:
    """True iff EVERY recorded error is a retryable transient — a citation-only
    miss or a transient model-output error (malformed/truncated JSON, LLMError).
    Substantive validation failures (word floor, placeholders, unlabelled
    resource claims, candidate-direction contamination) return False so the
    pipeline fails closed. This never loosens validation; it only decides whether
    one more bounded redraft is attempted before the topic is marked failed."""
    errs = getattr(exc, "errors", None) or []
    if not errs:
        return False
    retryable = _CITATION_ERROR_PREFIXES + _TRANSIENT_ERROR_PREFIXES
    return all(any(e.startswith(p) for p in retryable) for e in errs)


SYSTEM = (
    "You are an expert academic writing a section of a formal research proposal. "
    "Write complete, publication-quality prose — never an outline, never bullet "
    "stubs unless the section is a list of objectives. STRICT RULES:\n"
    "- The 'Topic' given in the prompt is the AUTHORITATIVE research subject. Write "
    "the entire proposal about that Topic. The client profile is background about "
    "the candidate ONLY — use it for fit/experience, never to change the research "
    "subject. If the profile mentions a different 'proposed PhD direction', research "
    "interest, or prior thesis, IGNORE it as the subject and still write about the "
    "Topic above.\n"
    "- Cite ONLY the evidence keys provided, using the format [@key]. Never cite a "
    "key that is not in the provided evidence list.\n"
    "- Never write bibliography or reference-list entries; citations are [@key] only.\n"
    "- Do NOT invent datasets, labs, participants, equipment, supervisors, "
    "institutional access, results, or candidate skills.\n"
    "- Any statement about future methods, data, or resources that is not evidenced "
    "MUST begin with 'Assumption:'.\n"
    "- No placeholders, no TODO, no [FILL IN], no [INSERT], no XXX.\n"
    "FORMATTING (the renderer styles headings/lists for you — output clean text):\n"
    "- Do NOT begin the text with the section title or any heading line, and do NOT "
    "use Markdown heading marks (#).\n"
    "- Do NOT use Markdown bold or italic markers (**, __, *). Write plain prose.\n"
    "- When multiple sources support one point, cite them in a single bracket "
    "'[@a; @b]', never as touching brackets '[@a][@b]'.\n"
    'Return ONLY JSON: {"text": "<the section prose>"}.'
)

# Per-section formatting instructions appended to the user prompt by section key.
SECTION_FORMAT_HINTS = {
    "title": (
        "Format: a single concise, specific proposal title (roughly 8–15 words) "
        "derived from the Topic above and the evidence — a focused research title, "
        "NOT a comma-separated list of fields, and NOT copied from any 'proposed "
        "direction' in the client profile. Output the title text only, no quotes, "
        "no 'Title:' prefix."),
    "objectives": (
        "Format: output ONLY a bullet list, one objective per line, each line "
        "beginning with '- ' and an infinitive verb (e.g. '- To identify ...'). "
        "No introductory sentence, 3–6 objectives."),
    "questions": (
        "Format: first the research questions, each on its own line labelled "
        "'RQ1:', 'RQ2:', ...; then the hypotheses, each on its own line labelled "
        "'H1:', 'H2:', .... No other prose."),
    "timeline": (
        "Format: one short framing sentence, then a bullet list of 6–8 work "
        "phases, each line beginning '- ' with the phase name followed by its "
        "span in parentheses as '(months A–B)' within the total duration "
        "(e.g. '- Systematic literature review (months 1–9)'). Phases must reflect "
        "THIS proposal's methodology; do not write a table."),
}


def _evidence_digest(evidence: list[dict], limit: int = 40) -> str:
    lines = []
    for e in evidence[:limit]:
        abstract = (e.get("abstract") or "")[:300]
        lines.append(
            f"[@{e['key']}] {e.get('title', '')} ({e.get('year', 'n.d.')}). "
            f"Relevance: {e.get('relevance_note', '')} Abstract: {abstract}"
        )
    return "\n".join(lines)


def _summary(text: str, words: int = 45) -> str:
    return " ".join((text or "").split()[:words])


def draft_section(llm, topic: Topic, config: EngineConfig, profile_text: str,
                  evidence: list[dict], section: dict, prior_summaries: dict[str, str],
                  forbidden_terms=(), evidence_blob: str = "") -> str:
    valid_keys = {e["key"] for e in evidence}
    topic_text = f"{topic.title} {topic.description}"
    require_cite = section["key"] in CITATION_REQUIRED
    word_floor = int(section.get("words", 150) * 0.5)
    prior = "\n".join(f"- {name}: {summ}" for name, summ in prior_summaries.items()) or "(none yet)"

    base_user = (
        f"Proposal type: {config.proposal_type}\nDiscipline: {config.discipline}\n"
        f"Target: {config.target or '(unspecified)'}\nDuration: {config.project_duration}\n"
        f"Topic (the authoritative research subject — write about THIS): {topic.title}\n"
        f"Topic detail: {topic.description or '(none)'}\n\n"
        f"Client profile — candidate background for fit ONLY, not the research "
        f"subject (may be empty):\n{profile_text[:1500] or '(no profile)'}\n\n"
        f"Prior section summaries:\n{prior}\n\n"
        f"Evidence you may cite (reference each by the bracketed key shown at the "
        f"start of its line):\n{_evidence_digest(evidence)}\n\n"
        f"Now write the '{section['name']}' section. Target ~{section.get('words', 150)} words."
    )
    if require_cite:
        base_user += " This section MUST cite at least one evidence key."
    hint = SECTION_FORMAT_HINTS.get(section["key"])
    if hint:
        base_user += "\n\n" + hint

    errors: list[str] = []
    for attempt in range(MAX_RETRIES + 1):
        user = base_user
        if errors:
            user += ("\n\nYour previous attempt was rejected for these reasons; fix ALL of them "
                     "and return valid JSON again:\n- " + "\n- ".join(errors))
        max_tokens = max(600, int(section.get("words", 150) * 6))
        try:
            data = llm.generate_json(SYSTEM, user, max_tokens=max_tokens)
        except LLMError as e:
            errors = [f"invalid JSON output: {e}"]
            continue
        text = (data.get("text") if isinstance(data, dict) else None) or ""
        text = text.strip()
        errors = validate_section(text, word_floor, valid_keys, require_citation=require_cite)
        contam = find_contamination(text, forbidden_terms, topic_text, evidence_blob)
        if contam:
            errors = errors + [
                "off-topic terms from the candidate's own proposed/prior research "
                "direction appear and are NOT part of the entered topic or the "
                "evidence — remove them and write strictly about the entered Topic: "
                + ", ".join(contam)]
        if not errors:
            return text
    raise DraftingFailed(section["key"], errors)


def draft_proposal(llm, topic: Topic, config: EngineConfig, profile_text: str,
                   evidence: list[dict], forbidden_terms=()) -> dict[str, str]:
    """Draft every non-skipped section. Returns {section_key: text}.

    ``forbidden_terms`` are distinctive terms from the candidate's own proposed
    research direction (see ``candidate_context``); any that surface in a section
    while absent from the topic and evidence trigger a redraft of that section.
    """
    from .candidate_context import evidence_blob as _blob
    blob = _blob(evidence)
    sections = {}
    prior_summaries: dict[str, str] = {}
    for spec in config.sections:
        s = spec.model_dump()
        if s["key"] in SKIP_DRAFT:
            continue
        text = draft_section(llm, topic, config, profile_text, evidence, s,
                             prior_summaries, forbidden_terms=forbidden_terms,
                             evidence_blob=blob)
        sections[s["key"]] = text
        prior_summaries[s["name"]] = _summary(text)
    return sections


_LEADING_HEADING_RE = re.compile(r"^\s*#{1,6}\s+.*(?:\r?\n|$)")


def _clean_title(text: str) -> str:
    """Strip any Markdown heading markers the model wrapped the title in, so the
    assembled H1 is a single '# Title' (never '# # Title'). Keeps the title text
    itself — only the leading '#'/'##' markers are removed."""
    return text.strip().lstrip("#").strip()


def _strip_leading_heading(body: str) -> str:
    """Remove a single leading Markdown heading line from a section body.

    Each section is drafted independently and the model often repeats the
    section title as its own heading; the engine already prints the heading, so
    the model's copy would duplicate it (and single-'#' copies get mis-parsed as
    the document title by the renderer). Drop exactly one leading heading line.
    """
    stripped = body.lstrip("\n")
    if stripped.lstrip().startswith("#"):
        return _LEADING_HEADING_RE.sub("", stripped, count=1).strip()
    return body.strip()


def render_draft_md(topic: Topic, config: EngineConfig, sections: dict[str, str]) -> str:
    """Assemble proposal_draft.md with Markdown headings and [@key] citations.

    The title section becomes the H1; a trailing '## References' heading is left
    for the bibliography stage / citeproc to fill.
    """
    parts: list[str] = []
    title_text = _clean_title(sections.get("title", topic.title)) or topic.title.strip()
    parts.append(f"# {title_text}\n")
    for spec in config.sections:
        key = spec.key
        if key in ("title", "references"):
            continue
        body = sections.get(key)
        if body is None:
            continue
        body = _strip_leading_heading(body)
        parts.append(f"## {spec.name}\n\n{body}\n")
    parts.append("## References\n")
    return "\n".join(parts)


def write_draft(topic: Topic, config: EngineConfig, sections: dict[str, str],
                out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_draft_md(topic, config, sections), encoding="utf-8")
    return out
