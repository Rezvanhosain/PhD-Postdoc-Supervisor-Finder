"""Stage 7 — Review checklist generation and approval."""
from __future__ import annotations

from pathlib import Path

from .bibliography import VERIFIED
from .topics import Topic
from .validators import find_placeholders


def build_checklist(topic: Topic, evidence: list[dict], audit_rows: list[dict],
                    draft_md: str, evidence_minimum: int) -> str:
    placeholders = find_placeholders(draft_md)
    n_evidence = len(evidence)
    verified = sum(1 for r in audit_rows if r["status"] == VERIFIED)
    needs_review = [r for r in audit_rows if r["needs_human_review"]]
    assumptions = draft_md.lower().count("assumption:")
    spot = audit_rows[:3]

    lines = [
        f"# Review Checklist — {topic.title}", "",
        f"- [{'x' if not placeholders else ' '}] No placeholders confirmed "
        f"({len(placeholders)} found)",
        f"- [{'x' if n_evidence >= evidence_minimum else ' '}] Evidence threshold met "
        f"({n_evidence} / {evidence_minimum})",
        f"- [{'x' if audit_rows else ' '}] Citation audit attached "
        f"({verified}/{len(audit_rows)} verified, {len(needs_review)} need human review)",
        f"- [{'x' if assumptions else ' '}] Assumptions clearly labelled "
        f"({assumptions} 'Assumption:' statements)",
        "- [ ] Research gap plausible (human judgement required)",
        "- [ ] Timeline sane (human judgement required)",
        "", "## 3 references to spot-check manually", "",
    ]
    if spot:
        for r in spot:
            lines.append(f"- **[@{r['key']}]** {r['title']} ({r['year']}) — "
                         f"status: {r['status']}; DOI: {r['doi'] or '—'}")
    else:
        lines.append("- (no citations were used in the proposal body)")

    if needs_review:
        lines += ["", "## Citations needing human review", ""]
        for r in needs_review:
            lines.append(f"- [@{r['key']}] {r['status']}: {r['note']}")
    return "\n".join(lines) + "\n"


def write_checklist(text: str, out_path: str | Path) -> Path:
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out
