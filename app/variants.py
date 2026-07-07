"""Proposal and email variants for one opportunity + supervisor pair.

Hard rules, enforced structurally rather than by prompt hope:
  * References: only citations that came from OpenAlex/Semantic Scholar and
    re-verified via Crossref/DOI metadata appear in a bibliography; anything
    else goes to the source audit marked NEEDS MANUAL REVIEW.
  * Emails: no draft is produced when the outreach gate blocks the pairing.
    Templates avoid stock AI phrases; a lint check rejects banned phrases in
    the final text (including LLM rewrites). Without an LLM key, drafts are
    generated from templates and clearly marked 'Template fallback: needs
    human rewrite'."""
from __future__ import annotations

import json
import re
from datetime import datetime

from app import llm
from app.config import OUTPUT_DIR
from app.db import insert, now
from app.references import (audit_table, collect_verified, format_reference,
                            verify_reference)

BANNED_PHRASES = (
    "i hope this email finds you well", "hope this finds you well",
    "deeply passionate", "esteemed", "cutting-edge", "cutting edge",
    "synergy", "world-renowned", "prestigious institution",
    "i am reaching out to you", "keen interest in your groundbreaking",
    "groundbreaking", "delve",
)


def banned_phrases_in(text: str) -> list[str]:
    low = (text or "").lower()
    return [p for p in BANNED_PHRASES if p in low]


# ---------------------------------------------------------------- proposals

_ANGLES = [
    ("supervisor-aligned", "extends the supervisor's documented research areas "
     "toward the candidate's own field"),
    ("opportunity-focused", "answers the call/ad text directly with the "
     "candidate's strongest existing expertise"),
    ("method-contribution", "same substantive area, but leads with a specific "
     "methodological contribution the candidate can credibly deliver"),
]


def proposal_variants(profile: dict, pos: dict, sup: dict | None,
                      topic: str, style: str = "APA 7") -> dict:
    """Three proposal ideas with verified-only bibliographies + source audit.

    Returns {"variants": [...], "audit": md, "verified": n, "flagged": n,
             "llm": bool, "file": path}."""
    refs = [verify_reference(r) for r in collect_verified(topic, limit=10)]
    verified = [r for r in refs if r.get("verified")]
    flagged = [r for r in refs if not r.get("verified")]
    bib = [format_reference(r, style) for r in verified]

    sup_areas: list[str] = []
    if sup:
        a = sup.get("research_areas") or "[]"
        sup_areas = json.loads(a) if isinstance(a, str) else a

    variants: list[dict] = []
    for i, (angle, rationale) in enumerate(_ANGLES, 1):
        variants.append({
            "angle": angle,
            "title": f"[FILL IN working title #{i}] — {topic[:70]}",
            "rationale": rationale + (
                f". Supervisor's documented areas: {', '.join(sup_areas[:4])}."
                if angle == "supervisor-aligned" and sup_areas else
                f". Opportunity: {pos.get('title','')[:100]}."),
            "research_gap": "[FILL IN — state the gap using only the verified "
                            "sources listed below]",
            "research_questions": ["[FILL IN RQ1]", "[FILL IN RQ2]"],
            "method": "[FILL IN — method the candidate can credibly execute]",
            "expected_contribution": "[FILL IN]",
            "timeline": "Year 1: literature review + design; Year 2: data "
                        "collection; Year 3: analysis, writing, submission. "
                        "(Adjust to the programme length.)",
            "references": bib,
            "template_fallback": True,
        })

    used_llm = False
    if llm.available():
        raw = llm.complete(
            "You draft three distinct PhD/postdoc proposal ideas. Return JSON: a list "
            "of 3 objects with keys title, rationale, research_gap, research_questions "
            "(list), method, expected_contribution, timeline. Cite ONLY works from the "
            "provided verified reference list, as (Author, Year). Never invent a "
            "reference or DOI.",
            json.dumps({"topic": topic,
                        "candidate_areas": profile.get("research_areas", []),
                        "opportunity": {k: pos.get(k, "") for k in
                                        ("title", "university", "description", "funding")},
                        "supervisor_areas": sup_areas,
                        "angles": [a for a, _ in _ANGLES],
                        "verified_references": bib})[:12000],
            max_tokens=3000)
        if raw:
            try:
                parsed = json.loads(re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M))
                for i, v in enumerate(parsed[:3]):
                    if isinstance(v, dict) and v.get("title"):
                        keep = variants[i]
                        keep.update({k: v[k] for k in
                                     ("title", "rationale", "research_gap",
                                      "research_questions", "method",
                                      "expected_contribution", "timeline") if k in v})
                        keep["template_fallback"] = False
                used_llm = True
            except Exception:
                pass  # keep templates; they are already honest placeholders

    audit = audit_table(refs)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = OUTPUT_DIR / f"proposal_variants_{stamp}.md"
    lines = [f"# Proposal variants — {topic}", f"Generated {now()}",
             f"Opportunity: {pos.get('title','')} — {pos.get('university','')}", ""]
    for v in variants:
        lines += [f"## {v['angle']}: {v['title']}",
                  ("**TEMPLATE FALLBACK: needs human rewrite**" if v["template_fallback"] else ""),
                  f"**Rationale:** {v['rationale']}",
                  f"**Gap:** {v['research_gap']}",
                  "**Research questions:** " + "; ".join(v["research_questions"]),
                  f"**Method:** {v['method']}",
                  f"**Contribution:** {v['expected_contribution']}",
                  f"**Timeline:** {v['timeline']}",
                  "**References (verified only):**"]
        lines += ["- " + b for b in v["references"]] or ["- (none verified — search again)"]
        lines.append("")
    lines += ["## Source audit", audit]
    path.write_text("\n".join(lines), encoding="utf-8")
    insert("documents", doc_type="proposal_variants", title=topic[:120],
           path=str(path), related_kind="position", related_id=pos.get("id", 0),
           meta=json.dumps({"verified": len(verified), "needs_review": len(flagged),
                            "llm": used_llm}),
           created_at=now())
    return {"variants": variants, "audit": audit, "verified": len(verified),
            "flagged": len(flagged), "llm": used_llm, "file": str(path)}


# ---------------------------------------------------------------- emails

def _verified_pub_line(sup: dict) -> str:
    pubs = sup.get("publications") or "[]"
    pubs = json.loads(pubs) if isinstance(pubs, str) else pubs
    for p in pubs:
        if p.get("verified"):
            venue = f" ({p['venue']}, {p.get('year','')})" if p.get("venue") else \
                f" ({p.get('year','')})" if p.get("year") else ""
            return f"I read your article \"{p.get('title','')}\"{venue}. "
    return ""


def email_variants(profile: dict, pos: dict, sup: dict) -> dict:
    """Three editable drafts for one gated pairing. Blocked gate = no drafts.

    Returns {"blocked": bool, "gate": {...}, "drafts": [...], "llm": bool}."""
    from app.vetting import outreach_gate
    gate = outreach_gate(profile, pos, sup)
    if not gate["allowed"]:
        return {"blocked": True, "gate": gate, "drafts": [],
                "warning": "Outreach gate BLOCKED this pairing — no drafts "
                           "generated: " + "; ".join(gate["reasons"])}

    name = sup.get("name", "")
    surname = name.split()[-1] if name else ""
    level = profile.get("target_level", "PhD")
    my_areas = ", ".join(profile.get("research_areas", [])[:3]) or "[your areas]"
    topic = pos.get("title", "")[:80]
    sim = gate.get("topic_similarity", 0)
    # honest-fit line: if adjacency rather than direct overlap, say so
    fit_line = ("My background is adjacent rather than identical to your area; "
                "I want to be upfront about that. " if 0.05 <= sim < 0.15 else "")
    pub_line = _verified_pub_line(sup)
    sig = f"\n\nKind regards,\n{profile.get('name','')}\n{profile.get('email','')}"

    drafts = [
        {"variant": "short_direct",
         "subject": f"{level} inquiry — {topic}",
         "body": f"Dear Professor {surname},\n\n"
                 f"Are you accepting {level} applicants for "
                 f"\"{pos.get('title','the advertised position')}\" at "
                 f"{pos.get('university','your institution')}? "
                 f"My research background is in {my_areas}. {fit_line}"
                 f"My CV is attached; happy to send a short proposal if useful."
                 + sig},
        {"variant": "research_fit",
         "subject": f"{level} applicant — research fit with your group",
         "body": f"Dear Professor {surname},\n\n{pub_line}"
                 f"I work on {my_areas}. {fit_line}"
                 f"I would like to apply for \"{pos.get('title','')}\" under your "
                 f"supervision, and can share a two-page proposal sketch on request. "
                 f"Could we discuss whether the fit is worth pursuing?" + sig},
        {"variant": "funding_specific",
         "subject": f"Application to {pos.get('title','the advertised call')[:60]}",
         "body": f"Dear Professor {surname},\n\n"
                 f"I am preparing an application for \"{pos.get('title','')}\""
                 + (f" ({pos.get('funding','')[:120]})" if pos.get("funding") else "")
                 + (f", deadline {pos['deadline']}" if pos.get("deadline") else "")
                 + f". My background: {my_areas}. {fit_line}"
                 f"Before submitting, may I confirm you are taking new {level} "
                 f"candidates on this call, and whether my profile is in scope?" + sig},
    ]

    used_llm = False
    if llm.available():
        for d in drafts:
            improved = llm.complete(
                "Tighten this academic outreach email. Under 140 words, plain and "
                "specific. Keep every factual claim exactly as given; add nothing. "
                "Forbidden phrases: " + "; ".join(BANNED_PHRASES) +
                ". Return only the email body.",
                d["body"], max_tokens=400)
            if improved and not banned_phrases_in(improved):
                d["body"] = improved.strip()
                used_llm = True

    for d in drafts:
        bad = banned_phrases_in(d["subject"] + " " + d["body"])
        if bad:  # defensive: should never fire for templates
            d["body"] = "[REWRITE REQUIRED — banned phrases removed: " \
                        + ", ".join(bad) + "]\n\n" + d["body"]
        d["template_fallback"] = not used_llm
        d["note"] = ("Template fallback: needs human rewrite before sending."
                     if not used_llm else
                     "LLM-polished draft — still requires manual review before sending.")
        d["id"] = insert("email_log", status="draft", provider="",
                         recipient=sup.get("email", ""), subject=d["subject"],
                         body=d["body"], related_kind="supervisor",
                         related_id=sup.get("id", 0), position_id=pos.get("id", 0),
                         supervisor_id=sup.get("id", 0), created_at=now())
    return {"blocked": False, "gate": gate, "drafts": drafts, "llm": used_llm}
