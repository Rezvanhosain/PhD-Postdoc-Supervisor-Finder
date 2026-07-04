"""Matching engine: scores the candidate profile against supervisors and
positions.

Primary method: TF-IDF cosine similarity (scikit-learn, fully offline).
If an OpenAI-compatible key is configured, embedding similarity is blended in.
Component scores are kept so the UI can explain every match."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Optional

from app.config import get_setting
from app.db import insert, log_error, now, rows

STOP = set("the a an and or of in for with on to at by is are as from this that".split())


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z][a-z\-]{2,}", text.lower()) if t not in STOP}


def keyword_overlap(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def tfidf_similarity(a: str, b: str) -> float:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity

        vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        m = vec.fit_transform([a, b])
        return float(cosine_similarity(m[0], m[1])[0][0])
    except Exception:
        return keyword_overlap(a, b)


def embedding_similarity(a: str, b: str) -> Optional[float]:
    """Optional: cosine similarity via an OpenAI-compatible embeddings API."""
    if not get_setting("OPENAI_API_KEY"):
        return None
    try:
        import httpx

        base = (get_setting("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        resp = httpx.post(f"{base}/embeddings", timeout=30, headers={
            "Authorization": f"Bearer {get_setting('OPENAI_API_KEY')}"},
            json={"model": "text-embedding-3-small", "input": [a[:6000], b[:6000]]})
        resp.raise_for_status()
        e1, e2 = (d["embedding"] for d in resp.json()["data"])
        dot = sum(x * y for x, y in zip(e1, e2))
        n1 = sum(x * x for x in e1) ** 0.5
        n2 = sum(x * x for x in e2) ** 0.5
        return dot / (n1 * n2) if n1 and n2 else 0.0
    except Exception as e:
        log_error("api", f"Embedding call failed, falling back to TF-IDF: {e}")
        return None


def deadline_urgency(deadline: str) -> tuple[float, str]:
    """Score 0..1 (1 = comfortable time left) and a note."""
    if not deadline:
        return 0.5, "No deadline listed — verify on the source page."
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d/%m/%Y", "%B %d, %Y"):
        try:
            d = datetime.strptime(deadline.strip(), fmt).date()
            days = (d - date.today()).days
            if days < 0:
                return 0.0, f"Deadline appears to have passed ({deadline})."
            if days < 14:
                return 0.3, f"Urgent: only {days} days until deadline."
            return 1.0, f"{days} days until deadline."
        except ValueError:
            continue
    return 0.5, f"Could not parse deadline '{deadline}' — check manually."


def profile_text(profile: dict) -> str:
    parts = (profile.get("research_areas", []) + profile.get("keywords", [])
             + profile.get("publications", [])[:10] + profile.get("skills", [])[:15])
    return " ".join(parts)


def score_supervisor(profile: dict, sup: dict) -> dict:
    areas = json.loads(sup.get("research_areas") or "[]") if isinstance(
        sup.get("research_areas"), str) else sup.get("research_areas", [])
    pubs = json.loads(sup.get("publications") or "[]") if isinstance(
        sup.get("publications"), str) else sup.get("publications", [])
    sup_text = " ".join(areas) + " " + " ".join(p.get("title", "") for p in pubs)
    cand_text = profile_text(profile)

    sim = tfidf_similarity(cand_text, sup_text) if sup_text.strip() else 0.0
    emb = embedding_similarity(cand_text, sup_text) if sup_text.strip() else None
    research = 0.6 * sim + 0.4 * emb if emb is not None else sim

    country_pref = [c.strip().lower() for c in profile.get("target_countries", []) if c.strip()]
    country_fit = 1.0 if not country_pref else (
        1.0 if (sup.get("country") or "").lower() in country_pref else 0.3)

    components = {"research_similarity": round(research, 3),
                  "country_fit": country_fit,
                  "method": "tfidf+embeddings" if emb is not None else "tfidf"}
    score = round(100 * (0.8 * research + 0.2 * country_fit), 1)

    overlap = sorted(_tokens(cand_text) & _tokens(sup_text))[:8]
    why = (f"Shared research vocabulary: {', '.join(overlap)}." if overlap
           else "Limited direct overlap detected — match is based on broad similarity.")
    risks = []
    if not areas and not pubs:
        risks.append("No publication data collected yet — fetch recent works before contacting.")
    if country_pref and country_fit < 1:
        risks.append("Institution is outside your target countries.")
    if not sup.get("email"):
        risks.append("No public email found — check the university profile page.")
    if score < 35:
        risks.append("Low similarity score — treat as exploratory only.")

    return {
        "score": score,
        "why": why,
        "risks": risks,
        "email_angle": (f"Reference their work on {areas[0]}" if areas else
                        "Ask whether they are accepting PhD/postdoc applicants in your area"),
        "components": components,
        "confidence": "low" if score < 35 or (not areas and not pubs) else "normal",
    }


def score_position(profile: dict, pos: dict) -> dict:
    pos_text = " ".join(filter(None, [pos.get("title"), pos.get("description"),
                                      pos.get("department"), pos.get("eligibility")]))
    cand_text = profile_text(profile)
    sim = tfidf_similarity(cand_text, pos_text) if pos_text.strip() else 0.0
    urgency, deadline_note = deadline_urgency(pos.get("deadline", ""))

    country_pref = [c.strip().lower() for c in profile.get("target_countries", []) if c.strip()]
    country_fit = 1.0 if not country_pref else (
        1.0 if (pos.get("country") or "").lower() in country_pref else 0.3)

    level = profile.get("target_level", "PhD").lower()
    title_low = (pos.get("title") or "").lower()
    level_fit = 1.0
    if "postdoc" in level and "phd" in title_low and "postdoc" not in title_low:
        level_fit = 0.4
    if level == "phd" and "postdoc" in title_low:
        level_fit = 0.4

    score = round(100 * (0.6 * sim + 0.15 * country_fit + 0.15 * level_fit + 0.1 * urgency), 1)
    overlap = sorted(_tokens(cand_text) & _tokens(pos_text))[:8]
    risks = []
    if not pos.get("deadline"):
        risks.append("Deadline missing — confirm on the source page before applying.")
    if level_fit < 1:
        risks.append("Position level may not match your target degree level.")
    if score < 35:
        risks.append("Low similarity — read the full advert before investing time.")

    return {
        "score": score,
        "why": (f"Overlapping keywords: {', '.join(overlap)}." if overlap
                else "Match based on general text similarity only."),
        "risks": risks,
        "email_angle": "Address the specific project/role named in the advert",
        "deadline_note": deadline_note,
        "components": {"similarity": round(sim, 3), "country_fit": country_fit,
                       "level_fit": level_fit, "deadline_urgency": urgency},
        "confidence": "low" if score < 35 else "normal",
    }


def run_matching(profile: dict) -> dict:
    """Score everything in the DB, persist match rows, return counts."""
    from app.db import execute

    execute("DELETE FROM matches")
    n_sup = n_pos = 0
    for sup in rows("SELECT * FROM supervisors"):
        r = score_supervisor(profile, sup)
        insert("matches", kind="supervisor", target_id=sup["id"], score=r["score"],
               reasons=json.dumps(r), confidence=r["confidence"], created_at=now())
        n_sup += 1
    for pos in rows("SELECT * FROM positions WHERE review_status != 'hidden'"):
        r = score_position(profile, pos)
        insert("matches", kind="position", target_id=pos["id"], score=r["score"],
               reasons=json.dumps(r), confidence=r["confidence"], created_at=now())
        n_pos += 1
    return {"supervisors": n_sup, "positions": n_pos}
