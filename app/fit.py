"""Fit scoring (workflow step 5) — tied to *selected* opportunities.

Unlike v1's global matching, fit runs only on the user's shortlist and scores
candidate <-> opportunity <-> supervisor triples. Every score is decomposed
into named components so the UI can explain it, and the classification from
step 2 drives whether supervisor outreach is required/recommended/optional."""
from __future__ import annotations

import json

from app.classify import LABELS
from app.db import execute, insert, now, rows
from app.matching import (_tokens, deadline_urgency, profile_text,
                          tfidf_similarity)

RECOMMENDATIONS = ("strong", "moderate", "weak", "avoid")

# classification -> (outreach required, outreach useful even if not required)
_OUTREACH = {
    "supervisor_required": (True, True),
    "supervisor_recommended": (False, True),
    "direct_application": (False, False),   # useful only when supervisor fit is high
    "named_pi_postdoc": (True, True),
    "open_call_postdoc": (False, True),
}


def _sup_text(sup: dict) -> str:
    areas = sup.get("research_areas") or "[]"
    pubs = sup.get("publications") or "[]"
    areas = json.loads(areas) if isinstance(areas, str) else areas
    pubs = json.loads(pubs) if isinstance(pubs, str) else pubs
    return " ".join(areas) + " " + " ".join(p.get("title", "") for p in pubs)


def score_fit(profile: dict, pos: dict, sup: dict | None = None) -> dict:
    """Score one (opportunity, supervisor?) pair against the profile."""
    cand_text = profile_text(profile)
    pos_text = " ".join(filter(None, [pos.get("title"), pos.get("description"),
                                      pos.get("department"), pos.get("field"),
                                      pos.get("eligibility")]))
    pos_sim = tfidf_similarity(cand_text, pos_text) if pos_text.strip() else 0.0

    sup_sim = None
    if sup:
        st = _sup_text(sup)
        sup_sim = tfidf_similarity(cand_text, st) if st.strip() else 0.0

    # level fit
    level = (profile.get("target_level") or "PhD").lower()
    kind = (pos.get("kind") or "").lower()
    level_fit = 1.0
    if kind:
        if "postdoc" in level and kind == "phd":
            level_fit = 0.3
        if level == "phd" and kind == "postdoc":
            level_fit = 0.3

    # country/university preference
    prefs = [c.strip().lower() for c in profile.get("target_countries", []) if c.strip()]
    from app.europe import to_code
    pos_cc = to_code(pos.get("country") or "").lower()
    country_fit = 1.0 if not prefs else (
        1.0 if (pos.get("country") or "").lower() in prefs or pos_cc in prefs else 0.4)

    urgency, deadline_note = deadline_urgency(pos.get("deadline", ""))

    classification = pos.get("classification") or ""
    required, useful = _OUTREACH.get(classification, (False, True))
    outreach_useful = required or useful or (sup_sim is not None and sup_sim > 0.25)

    if sup_sim is not None:
        research = 0.5 * pos_sim + 0.5 * sup_sim
    else:
        research = pos_sim
    score = round(100 * (0.55 * research + 0.15 * level_fit
                         + 0.15 * country_fit + 0.15 * urgency), 1)

    if score >= 60:
        rec = "strong"
    elif score >= 40:
        rec = "moderate"
    elif score >= 22:
        rec = "weak"
    else:
        rec = "avoid"

    overlap = sorted(_tokens(cand_text) & _tokens(pos_text + (" " + _sup_text(sup) if sup else "")))[:10]
    why_parts = []
    if overlap:
        why_parts.append(f"Shared research vocabulary: {', '.join(overlap)}.")
    if sup_sim is not None:
        why_parts.append(f"Supervisor topic similarity {sup_sim:.2f} "
                         f"({'good' if sup_sim > 0.2 else 'limited'} overlap with "
                         f"{sup.get('name','the PI')}'s documented work).")
    if classification:
        why_parts.append(f"Admission path: {LABELS.get(classification, classification)} "
                         f"(confidence {pos.get('class_confidence', 0)}, "
                         f"{'official' if pos.get('class_source_official') else 'third-party'} source).")
    why = " ".join(why_parts) or "Match is based on broad text similarity only."

    risks = []
    if research < 0.1:
        risks.append("Very low topical overlap — read the full advert before investing time.")
    if level_fit < 1:
        risks.append("Opportunity level may not match your target degree level.")
    if country_fit < 1:
        risks.append("Outside your preferred countries.")
    if urgency == 0.0:
        risks.append("Deadline appears to have passed — verify on the official page.")
    elif urgency <= 0.3:
        risks.append(deadline_note)
    if sup and not sup.get("email"):
        risks.append("No public email for this supervisor — check the official profile page.")
    if sup and sup.get("source_type") != "official":
        risks.append("Supervisor record is bibliometric (OpenAlex), not from an official "
                     "university page — verify they still work there and supervise students.")
    if classification and pos.get("class_confidence", 0) < 0.4:
        risks.append("Admission-path classification is low-confidence — confirm on the "
                     "official admissions page.")

    return {
        "score": score, "recommendation": rec,
        "outreach_required": required, "outreach_useful": bool(outreach_useful),
        "why": why, "risks": risks, "deadline_note": deadline_note,
        "components": {
            "opportunity_similarity": round(pos_sim, 3),
            "supervisor_similarity": round(sup_sim, 3) if sup_sim is not None else None,
            "level_fit": level_fit, "country_fit": country_fit,
            "deadline_urgency": urgency,
        },
    }


def run_fit_for_shortlist(profile: dict) -> int:
    """Score every shortlisted opportunity, alone and paired with each of its
    discovered supervisors. Persists to fit_scores. Returns rows written."""
    n = 0
    for pos in rows("SELECT * FROM positions WHERE shortlisted=1"):
        pairs: list[dict | None] = [None]
        pairs += rows("SELECT * FROM supervisors WHERE position_id=?", (pos["id"],))
        for sup in pairs:
            r = score_fit(profile, pos, sup)
            sid = sup["id"] if sup else 0
            execute("DELETE FROM fit_scores WHERE position_id=? AND supervisor_id=?",
                    (pos["id"], sid))
            insert("fit_scores", position_id=pos["id"], supervisor_id=sid,
                   score=r["score"], recommendation=r["recommendation"],
                   outreach_useful=int(r["outreach_useful"]),
                   reasons=json.dumps(r), created_at=now())
            n += 1
    return n
