"""Workflow-specific document bundles (workflow step 6).

v1 had one generic flow; v2 generates the *right* set of documents for the
admission path classified in step 2:

  A. supervisor-first PhD  -> tailored CV + supervisor email + concept note
  B. direct-application PhD -> tailored CV + statement of purpose
                               (+ proposal if required/strategic, + optional
                                supervisor email when fit says it is useful)
  C. postdoc               -> tailored CV + cover letter / PI email +
                               research statement (+ proposal only if needed)

All content rules from v1 still apply: facts come only from the stored
profile and verified API data; unverifiable references go to the audit file,
never into final documents."""
from __future__ import annotations

import json

from app import llm
from app.db import insert, now, rows
from app.docgen.generators import (_save_doc, generate_cv, generate_email,
                                   generate_proposal)
from app.docgen.writers import Block
from app.references import collect_verified, verify_reference

# classification label -> bundle type
BUNDLE_FOR = {
    "supervisor_required": "A",
    "supervisor_recommended": "A",
    "direct_application": "B",
    "named_pi_postdoc": "C",
    "open_call_postdoc": "C",
}
BUNDLE_NAMES = {
    "A": "Supervisor-first PhD (CV + supervisor email + concept note)",
    "B": "Direct-application PhD (CV + statement of purpose [+ proposal/email])",
    "C": "Postdoc (CV + cover letter/PI email + research statement)",
}


def _llm_or(default: str, system: str, user: str, max_tokens: int = 900) -> str:
    if llm.available():
        out = llm.complete(system, user, max_tokens=max_tokens)
        if out:
            return out.strip()
    return default


def _pos_line(pos: dict) -> str:
    return f"{pos.get('title','')} at {pos.get('university','')} ({pos.get('country','')})"


def generate_statement_of_purpose(profile: dict, pos: dict) -> dict:
    """Statement of purpose / motivation letter for a direct-application PhD."""
    facts = {k: profile.get(k) for k in
             ("research_areas", "education", "publications", "skills", "work_experience")}
    skeleton = (
        f"I am applying for {_pos_line(pos)}. My research interests in "
        f"{', '.join(profile.get('research_areas', [])[:3]) or '[your areas]'} align with "
        f"this programme.\n\n[FILL IN: motivation — why this programme, why this "
        f"university, why now.]\n\n[FILL IN: relevant experience — draw on your "
        f"education and publications.]\n\n[FILL IN: goals after the PhD.]")
    text = _llm_or(
        skeleton,
        "You draft a statement of purpose for a PhD application. Use ONLY the facts "
        "provided; never invent publications, grades or experience. Where information "
        "is missing, write [FILL IN: ...]. 400-600 words, first person, plain text.",
        json.dumps({"opportunity": {k: pos.get(k) for k in
                                    ("title", "university", "country", "description")},
                    "candidate_facts": facts}, default=str)[:9000], max_tokens=1200)
    blocks: list[Block] = [("h1", "Statement of Purpose"),
                           ("p", f"Application: {_pos_line(pos)}"), ("p", "")]
    blocks += [("p", para) for para in text.split("\n\n")]
    return _save_doc("statement_of_purpose", pos.get("title", "sop"), blocks,
                     related_kind="position", related_id=pos.get("id", 0))


def generate_research_statement(profile: dict, pos: dict,
                                sup: dict | None = None) -> dict:
    """Research statement / project-fit note for a postdoc application."""
    sup_note = ""
    if sup:
        areas = sup.get("research_areas") or "[]"
        areas = json.loads(areas) if isinstance(areas, str) else areas
        if areas:
            sup_note = (f"Documented research areas of {sup.get('name','the PI')}: "
                        f"{', '.join(areas[:5])} (source: {sup.get('source_url','')}).")
    skeleton = (
        f"Research statement for {_pos_line(pos)}.\n\n"
        f"[FILL IN: summary of your research trajectory to date.]\n\n"
        f"[FILL IN: how your work connects to this project/group. {sup_note}]\n\n"
        f"[FILL IN: what you would contribute in the first year.]")
    text = _llm_or(
        skeleton,
        "You draft a postdoc research statement / project-fit note. Use ONLY the facts "
        "provided; never invent results, papers or the PI's interests beyond the "
        "documented areas given. Missing info -> [FILL IN: ...]. 350-500 words.",
        json.dumps({"opportunity": {k: pos.get(k) for k in
                                    ("title", "university", "description")},
                    "pi_documented_areas": sup_note,
                    "candidate_facts": {k: profile.get(k) for k in
                                        ("research_areas", "publications", "skills")}},
                   default=str)[:9000], max_tokens=1100)
    blocks: list[Block] = [("h1", "Research Statement"),
                           ("p", f"Position: {_pos_line(pos)}")]
    if sup_note:
        blocks.append(("p", sup_note))
    blocks += [("p", para) for para in text.split("\n\n")]
    return _save_doc("research_statement", pos.get("title", "statement"), blocks,
                     related_kind="position", related_id=pos.get("id", 0))


def generate_cover_letter(profile: dict, pos: dict, sup: dict | None = None) -> dict:
    """Postdoc cover letter (formal application letter, not the outreach email)."""
    to_line = f"Prof. {sup['name'].split()[-1]}" if sup and sup.get("name") else \
        "the selection committee"
    skeleton = (
        f"Dear {to_line},\n\n"
        f"I am writing to apply for {_pos_line(pos)}.\n\n"
        f"[FILL IN: 1 paragraph — your strongest relevant result/experience.]\n\n"
        f"[FILL IN: 1 paragraph — fit with the project and group.]\n\n"
        f"Kind regards,\n{profile.get('name','')}")
    text = _llm_or(
        skeleton,
        "You draft a formal postdoc application cover letter, max 350 words. Use ONLY "
        "the facts given; never invent achievements. Missing info -> [FILL IN: ...].",
        json.dumps({"opportunity": _pos_line(pos),
                    "description": (pos.get("description") or "")[:2000],
                    "candidate_facts": {k: profile.get(k) for k in
                                        ("name", "research_areas", "publications",
                                         "education", "skills")}}, default=str)[:9000])
    blocks: list[Block] = [("h1", "Cover Letter"), ("p", f"Re: {_pos_line(pos)}"), ("p", "")]
    blocks += [("p", para) for para in text.split("\n\n")]
    return _save_doc("cover_letter", pos.get("title", "cover"), blocks,
                     related_kind="position", related_id=pos.get("id", 0))


def generate_concept_note(profile: dict, pos: dict, topic: str,
                          sup: dict | None = None, style: str = "APA 7") -> dict:
    """Short research concept note for supervisor-first outreach: a compact
    proposal (verified references only) rather than the full v1 proposal."""
    refs = [verify_reference(r) for r in collect_verified(topic, limit=6)]
    verified = [r for r in refs if r.get("verified")]
    from app.references import audit_table, format_reference
    sup_note = ""
    if sup:
        areas = sup.get("research_areas") or "[]"
        areas = json.loads(areas) if isinstance(areas, str) else areas
        if areas:
            sup_note = (f"Proposed in alignment with {sup.get('name','')}'s documented "
                        f"areas: {', '.join(areas[:4])}.")
    blocks: list[Block] = [
        ("h1", f"Research Concept Note: {topic}"),
        ("p", f"Prepared for {_pos_line(pos)}. {sup_note}"),
        ("h2", "Research Idea"), ("p", "[FILL IN: 1 paragraph — the core question and why it matters.]"),
        ("h2", "Approach"), ("p", "[FILL IN: 1 paragraph — data/methods you would use.]"),
        ("h2", "Fit"), ("p", sup_note or "[FILL IN: why this group/university.]"),
        ("h2", f"Key Sources ({style})"),
    ]
    blocks += [("bullet", format_reference(r, style)) for r in verified] or \
        [("p", "No verified references found for this topic yet.")]
    result = _save_doc("concept_note", topic, blocks,
                       related_kind="position", related_id=pos.get("id", 0),
                       meta={"style": style, "verified": len(verified)})
    from pathlib import Path
    audit = Path(result["docx"]).with_name(Path(result["docx"]).stem + "_SOURCE_AUDIT.md")
    audit.write_text(f"# Source audit — {topic}\n\n" + audit_table(refs), encoding="utf-8")
    result["audit"] = str(audit)
    from app.references import save_citations
    save_citations(refs, result["id"])
    return result


def generate_bundle(profile: dict, pos: dict, sup: dict | None,
                    topic: str, style: str = "APA 7",
                    include_proposal: bool | None = None,
                    fit: dict | None = None) -> dict:
    """Generate the correct document set for the opportunity's admission path.

    Returns {bundle, documents: [...], email_id or None, notes: [...]}.
    Also links the produced files to the outreach draft (attachments column)
    and creates/updates the tracker row."""
    classification = pos.get("classification") or "direct_application"
    bundle = BUNDLE_FOR.get(classification, "B")
    docs: list[dict] = []
    notes: list[str] = []
    email_id = None

    cv = generate_cv(profile, target=pos)
    cv["kind"] = "cv"
    docs.append(cv)

    if bundle == "A":
        cn = generate_concept_note(profile, pos, topic, sup, style)
        cn["kind"] = "concept_note"
        docs.append(cn)
        if sup:
            em = generate_email(profile, sup, topic, position=pos)
            email_id = em["id"]
            if em.get("warning"):
                notes.append(em["warning"])
        else:
            notes.append("No supervisor selected — pick one in step 4 to draft the "
                         "outreach email (required for this admission path).")
    elif bundle == "B":
        sop = generate_statement_of_purpose(profile, pos)
        sop["kind"] = "statement_of_purpose"
        docs.append(sop)
        want_proposal = include_proposal
        if want_proposal is None:
            want_proposal = "proposal" in (pos.get("description") or "").lower()
        if want_proposal:
            refs = [verify_reference(r) for r in collect_verified(topic, limit=10)]
            pr = generate_proposal(profile, topic, refs, sup, style)
            pr["kind"] = "proposal"
            docs.append(pr)
        if sup and fit and fit.get("outreach_useful"):
            em = generate_email(profile, sup, topic, position=pos)
            email_id = em["id"]
            if em.get("warning"):
                notes.append(em["warning"])
            if email_id:
                notes.append("Direct application: supervisor email is optional but the "
                             "fit engine judged outreach useful here.")
    else:  # C — postdoc
        cl = generate_cover_letter(profile, pos, sup)
        cl["kind"] = "cover_letter"
        docs.append(cl)
        rs = generate_research_statement(profile, pos, sup)
        rs["kind"] = "research_statement"
        docs.append(rs)
        if include_proposal:
            refs = [verify_reference(r) for r in collect_verified(topic, limit=10)]
            pr = generate_proposal(profile, topic, refs, sup, style)
            pr["kind"] = "proposal"
            docs.append(pr)
        if sup:
            em = generate_email(profile, sup, topic, position=pos)
            email_id = em["id"]
            if em.get("warning"):
                notes.append(em["warning"])

    paths = [d.get("docx", "") for d in docs]
    if email_id:
        from app.db import execute
        execute("UPDATE email_log SET attachments=?, position_id=?, supervisor_id=? WHERE id=?",
                (json.dumps(paths), pos.get("id", 0), (sup or {}).get("id", 0), email_id))

    from app.tracker import ensure_application
    app_id = ensure_application(pos, sup, attachments=paths)
    return {"bundle": bundle, "bundle_name": BUNDLE_NAMES[bundle],
            "documents": docs, "email_id": email_id, "notes": notes,
            "application_id": app_id}
