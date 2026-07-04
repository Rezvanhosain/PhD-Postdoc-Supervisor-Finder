"""Generators for the four document types. All facts come from the stored
profile and verified API data; the optional LLM only rewords."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app import llm
from app.config import OUTPUT_DIR
from app.db import insert, now
from app.docgen.writers import Block, write_docx, write_pdf
from app.references import audit_table, format_reference


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text)[:40].strip("_") or "document"


def _save_doc(doc_type: str, title: str, blocks: list[Block],
              related_kind: str = "", related_id: int = 0,
              meta: dict | None = None) -> dict:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = OUTPUT_DIR / f"{doc_type}_{_slug(title)}_{stamp}"
    docx_path = write_docx(blocks, base.with_suffix(".docx"))
    pdf_path = write_pdf(blocks, base.with_suffix(".pdf"))
    doc_id = insert("documents", doc_type=doc_type, title=title, path=str(base),
                    related_kind=related_kind, related_id=related_id,
                    meta=json.dumps(meta or {}), created_at=now())
    return {"id": doc_id, "docx": str(docx_path), "pdf": str(pdf_path)}


# ---------------- A. ATS-optimized CV ----------------

def generate_cv(profile: dict, target: dict | None = None) -> dict:
    """Tailored CV. Only reorders/rewords the user's own facts."""
    target_desc = ""
    if target:
        target_desc = f"{target.get('title','')} at {target.get('university','')}"
    summary = (f"{profile.get('target_level','PhD')} candidate with research interests in "
               + ", ".join(profile.get("research_areas", [])[:4]) + ".")
    if llm.available():
        improved = llm.complete(
            "You improve the wording of a professional summary for an academic CV. "
            "Return 2-3 sentences of plain text only.",
            f"Target role: {target_desc or 'academic research position'}\n"
            f"Facts: {json.dumps({k: profile.get(k) for k in ('research_areas','degrees','skills','publications')}, default=str)[:3000]}")
        if improved:
            summary = improved.strip()

    blocks: list[Block] = [
        ("h1", profile.get("name", "Candidate")),
        ("p", " | ".join(filter(None, [profile.get("email", ""), profile.get("phone", "")]))),
        ("h2", "Professional Summary"), ("p", summary),
        ("h2", "Education"),
        *[("bullet", e) for e in profile.get("education", []) or ["[FILL IN education]"]],
        ("h2", "Research Interests"),
        ("p", ", ".join(profile.get("research_areas", []) or ["[FILL IN]"])),
    ]
    if profile.get("publications"):
        blocks.append(("h2", "Publications"))
        blocks += [("bullet", p) for p in profile["publications"][:15]]
    if profile.get("work_experience"):
        blocks.append(("h2", "Professional Experience"))
        blocks += [("bullet", w) for w in profile["work_experience"][:12]]
    if profile.get("teaching"):
        blocks.append(("h2", "Teaching Experience"))
        blocks += [("bullet", t) for t in profile["teaching"][:10]]
    if profile.get("skills"):
        blocks.append(("h2", "Skills"))
        blocks.append(("p", ", ".join(profile["skills"][:25])))
    return _save_doc("cv", target_desc or "general", blocks,
                     meta={"target": target_desc})


# ---------------- B. Research proposal ----------------

PROPOSAL_SECTIONS = ["Background", "Research Gap", "Research Questions", "Objectives",
                     "Literature Review", "Methodology", "Expected Contribution", "Timeline"]


def generate_proposal(profile: dict, topic: str, refs: list[dict],
                      supervisor: dict | None = None, style: str = "APA 7") -> dict:
    """Proposal skeleton with ONLY verified references. Unverified ones go to
    the audit table marked for manual review and are excluded from the list."""
    verified = [r for r in refs if r.get("verified")]
    flagged = [r for r in refs if not r.get("verified")]
    sup_note = ""
    if supervisor:
        areas = supervisor.get("research_areas", [])
        if isinstance(areas, str):
            areas = json.loads(areas or "[]")
        if areas:
            sup_note = (f"Aligned with {supervisor.get('name','the supervisor')}'s documented "
                        f"research areas: {', '.join(areas[:4])} (source: "
                        f"{supervisor.get('source_url','')}).")

    lit_lines = [f"{format_reference(r, style)}" for r in verified]
    body: dict[str, str] = {s: f"[FILL IN — draft your {s.lower()} here]" for s in PROPOSAL_SECTIONS}
    body["Literature Review"] = ("Key verified sources identified for this topic are listed "
                                 "below and in the References section. Synthesize them here.\n"
                                 + "\n".join("- " + l for l in lit_lines[:8]))
    if llm.available():
        draft = llm.complete(
            "You draft sections of a PhD research proposal. Return JSON mapping section "
            "names to 1-2 paragraph drafts. Cite ONLY from the provided verified reference "
            "list, using (Author, Year) form.",
            json.dumps({"topic": topic, "candidate_areas": profile.get("research_areas", []),
                        "supervisor_note": sup_note, "sections": PROPOSAL_SECTIONS,
                        "verified_references": lit_lines})[:12000], max_tokens=3000)
        if draft:
            try:
                parsed = json.loads(re.sub(r"^```(json)?|```$", "", draft.strip(), flags=re.M))
                for k, v in parsed.items():
                    if k in body and isinstance(v, str):
                        body[k] = v
            except Exception:
                pass

    blocks: list[Block] = [("h1", f"Research Proposal: {topic}")]
    if sup_note:
        blocks.append(("p", sup_note))
    for section in PROPOSAL_SECTIONS:
        blocks.append(("h2", section))
        blocks.append(("p", body[section]))
    blocks.append(("h2", f"References ({style})"))
    blocks += [("bullet", l) for l in lit_lines] or [("p", "No verified references found — "
                                                     "run a literature search first.")]
    result = _save_doc("proposal", topic, blocks,
                       meta={"style": style, "verified": len(verified),
                             "needs_review": len(flagged)})
    # source audit file
    audit_path = Path(result["docx"]).with_name(
        Path(result["docx"]).stem + "_SOURCE_AUDIT.md")
    audit_path.write_text(
        f"# Source audit — {topic}\n\nGenerated {now()}\n\n" + audit_table(refs),
        encoding="utf-8")
    result["audit"] = str(audit_path)
    from app.references import save_citations
    save_citations(refs, result["id"])
    return result


# ---------------- C. Project timeline ----------------

TIMELINES = {
    "3-year PhD": [
        ("Months 1-6", "Literature review; refine research questions; PhD training modules."),
        ("Months 6-9", "Finalize methodology; ethics approval application."),
        ("Months 9-12", "Pilot study; first-year progression review; conference abstract."),
        ("Months 12-20", "Main data collection."),
        ("Months 20-26", "Data analysis; first journal article submission."),
        ("Months 26-32", "Thesis writing; second paper; international conference presentation."),
        ("Months 32-36", "Final drafts, submission, viva preparation."),
    ],
    "4-year PhD": [
        ("Year 1", "Coursework and training; systematic literature review; proposal defense."),
        ("Year 2", "Methodology; ethics approval; pilot; first conference paper."),
        ("Year 3", "Main data collection and analysis; first journal submission."),
        ("Year 4", "Second paper; thesis writing; final submission and viva."),
    ],
    "2-year postdoc": [
        ("Months 1-3", "Onboarding; refine project plan with PI; ethics amendments."),
        ("Months 3-9", "Data collection / experiments; first manuscript drafted."),
        ("Months 9-15", "Analysis; conference presentations; grant proposal contribution."),
        ("Months 15-21", "Second manuscript; mentoring junior researchers."),
        ("Months 21-24", "Final outputs; project report; fellowship/next-position applications."),
    ],
}


def generate_timeline(kind: str, topic: str = "") -> dict:
    plan = TIMELINES.get(kind, TIMELINES["3-year PhD"])
    blocks: list[Block] = [("h1", f"{kind} Project Timeline" + (f" — {topic}" if topic else ""))]
    for period, activity in plan:
        blocks.append(("h2", period))
        blocks.append(("p", activity))
    blocks.append(("h2", "Standing milestones"))
    for m in ["Supervisor meetings every 2 weeks", "Annual progression reviews",
              "Ethics approval before any data collection",
              "Target: 1 conference + 1 journal submission per year (adjust per field)"]:
        blocks.append(("bullet", m))
    return _save_doc("timeline", kind, blocks, meta={"kind": kind})


# ---------------- D. Supervisor outreach email ----------------

def _areas_clause(supervisor: dict) -> str:
    areas = supervisor.get("research_areas", [])
    if isinstance(areas, str):
        try:
            areas = json.loads(areas or "[]")
        except json.JSONDecodeError:
            areas = []
    return f" on {', '.join(areas[:2])}" if areas else ""


def generate_email(profile: dict, supervisor: dict, topic: str) -> dict:
    """Draft outreach email. Mentions publications ONLY from the supervisor's
    verified publication list stored in the DB."""
    pubs = supervisor.get("publications", [])
    if isinstance(pubs, str):
        pubs = json.loads(pubs or "[]")
    verified_pubs = [p for p in pubs if p.get("verified")][:2]
    pub_line = ""
    if verified_pubs:
        p = verified_pubs[0]
        pub_line = (f"I read with interest your {p.get('year','recent')} article "
                    f"\"{p.get('title','')}\"" + (f" in {p['venue']}" if p.get("venue") else "") + ". ")

    name = supervisor.get("name", "Professor")
    degrees = ", ".join(profile.get("degrees", [])[:3])
    subject = f"Prospective {profile.get('target_level','PhD')} applicant — {topic[:60]}"
    body = (
        f"Dear Professor {name.split()[-1] if name else ''},\n\n"
        f"{pub_line}"
        f"I am writing to ask whether you are accepting {profile.get('target_level','PhD')} "
        f"applicants in the area of {topic}.\n\n"
        f"My background: {degrees or '[your degrees]'}; research interests in "
        f"{', '.join(profile.get('research_areas', [])[:3]) or '[your areas]'}. "
        f"I believe this aligns with your work{_areas_clause(supervisor)}.\n\n"
        f"I would propose to investigate: {topic}. A brief research proposal, my CV, and "
        f"transcripts are attached.\n\n"
        f"Thank you for your time — I would welcome the chance to discuss this.\n\n"
        f"Kind regards,\n{profile.get('name','')}\n{profile.get('email','')}\n\n"
        f"Attachments: CV, research proposal, transcripts"
    )
    if llm.available():
        improved = llm.complete(
            "Polish this academic outreach email. Keep it under 180 words, professional, "
            "not salesy. Keep every factual claim exactly as given; do not add publications "
            "or achievements. Return only the email body.",
            body, max_tokens=600)
        if improved:
            body = improved.strip()
    email_id = insert("email_log", status="draft", provider="", recipient=supervisor.get("email", ""),
                      subject=subject, body=body, related_kind="supervisor",
                      related_id=supervisor.get("id", 0), created_at=now())
    return {"id": email_id, "subject": subject, "body": body,
            "recipient": supervisor.get("email", ""),
            "warning": None if verified_pubs else
            "No verified publications on file for this supervisor — the email does not cite "
            "specific papers. Fetch their recent works first for a stronger opener."}
