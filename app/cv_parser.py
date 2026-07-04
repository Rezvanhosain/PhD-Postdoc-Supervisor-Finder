"""CV parsing for PDF/DOCX. Heuristic section-based extraction; always returns
a profile dict plus a list of warnings so the UI can flag low-confidence fields
for manual editing."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

from app.db import log_error

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(\+?\d[\d\s().-]{7,}\d)")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
DEGREE_RE = re.compile(
    r"\b(Ph\.?D\.?|Doctorate|DBA|Ed\.?D\.?|M\.?Sc\.?|MBA|M\.?A\.?|MPhil|M\.?Ed\.?|"
    r"B\.?Sc\.?|B\.?A\.?|BBA|Master(?:'s)?|Bachelor(?:'s)?)\b", re.I)

SECTION_ALIASES = {
    "education": ["education", "academic background", "qualifications", "academic qualifications"],
    "publications": ["publications", "published works", "research output", "journal articles",
                     "conference papers", "selected publications"],
    "skills": ["skills", "technical skills", "competencies", "key skills"],
    "teaching": ["teaching", "teaching experience", "courses taught", "lecturing"],
    "work": ["experience", "work experience", "employment", "professional experience",
             "employment history", "work history"],
    "research": ["research interests", "research areas", "areas of interest",
                 "research experience", "research focus"],
}

DISCIPLINE_KEYWORDS = [
    "business", "accounting", "finance", "management", "leadership", "education",
    "social science", "sociology", "ngo", "nonprofit", "non-profit", "public policy",
    "development studies", "governance", "entrepreneurship", "marketing", "economics",
    "human resource", "organizational behavior", "corporate governance", "microfinance",
    "sustainability", "csr", "public administration",
]


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import pdfplumber

        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    if suffix in (".docx", ".doc"):
        import docx2txt

        return docx2txt.process(str(path)) or ""
    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported file type: {suffix}. Please upload PDF or DOCX.")


def _split_sections(text: str) -> dict[str, str]:
    """Split raw text into named sections using heading heuristics."""
    lines = text.splitlines()
    sections: dict[str, list[str]] = {"_header": []}
    current = "_header"
    for line in lines:
        stripped = line.strip().rstrip(":").lower()
        matched = None
        if 0 < len(stripped) <= 45:
            for key, aliases in SECTION_ALIASES.items():
                if any(stripped == a or stripped.startswith(a) for a in aliases):
                    matched = key
                    break
        if matched:
            current = matched
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v).strip() for k, v in sections.items()}


def _bullets(block: str, max_items: int = 30) -> list[str]:
    items = []
    for line in block.splitlines():
        line = line.strip(" •-*•\t")
        if len(line) > 3:
            items.append(line)
    return items[:max_items]


def _guess_name(header: str, full_text: str) -> str:
    for line in header.splitlines()[:6]:
        line = line.strip()
        if (2 <= len(line.split()) <= 5 and len(line) < 60
                and not EMAIL_RE.search(line) and not any(ch.isdigit() for ch in line)
                and not re.search(r"curriculum|vitae|resume|cv\b", line, re.I)):
            return line
    return ""


def _keywords(text: str, extra: list[str]) -> list[str]:
    found = []
    low = text.lower()
    for kw in DISCIPLINE_KEYWORDS:
        if kw in low:
            found.append(kw)
    for kw in extra:
        k = kw.strip().lower()
        if k and k not in found:
            found.append(k)
    return found[:40]


def parse_cv(path: str | Path) -> Tuple[dict, list[str]]:
    """Return (profile, warnings). Never raises for content problems —
    unparseable areas produce warnings instead."""
    warnings: list[str] = []
    try:
        text = extract_text(path)
    except Exception as e:
        log_error("cv_parse", f"Failed to read CV: {e}", needs_review=True)
        raise
    if len(text.strip()) < 100:
        warnings.append("Very little text extracted — the CV may be scanned images. "
                        "Please fill in your profile manually.")
    sections = _split_sections(text)
    header = sections.get("_header", "")

    emails = EMAIL_RE.findall(text)
    name = _guess_name(header, text)
    if not name:
        warnings.append("Could not confidently detect your name — please check it.")
    if not emails:
        warnings.append("No email address found in the CV.")

    education = _bullets(sections.get("education", ""))
    degrees = sorted(set(m.group(0) for m in DEGREE_RE.finditer(text)))
    publications = [p for p in _bullets(sections.get("publications", "")) if YEAR_RE.search(p)]
    research_block = sections.get("research", "")
    research_areas = _bullets(research_block, 15)

    if not education:
        warnings.append("No Education section detected — please add it manually.")
    if not research_areas:
        warnings.append("No research interests detected — enter them in the "
                        "Research Interests page (needed for matching).")

    profile = {
        "name": name,
        "email": emails[0] if emails else "",
        "phone": (PHONE_RE.search(text) or [None]) and (PHONE_RE.search(text).group(1) if PHONE_RE.search(text) else ""),
        "education": education,
        "degrees": degrees,
        "research_areas": research_areas,
        "publications": publications,
        "skills": _bullets(sections.get("skills", "")),
        "teaching": _bullets(sections.get("teaching", "")),
        "work_experience": _bullets(sections.get("work", "")),
        "keywords": _keywords(text, research_areas),
        "target_countries": [],
        "target_level": "PhD",
        "raw_text": text[:20000],
        "parse_warnings": warnings,
    }
    for w in warnings:
        log_error("cv_parse", w, needs_review=True)
    return profile, warnings
