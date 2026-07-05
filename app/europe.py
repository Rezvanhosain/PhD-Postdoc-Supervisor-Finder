"""Europe scope: the app is Europe-only by design. Country helpers used by
search filters, supervisor discovery and fit scoring."""
from __future__ import annotations

# ISO 3166-1 alpha-2 -> display name. EU/EEA/EFTA + UK + candidate countries
# commonly listed on EURAXESS.
EUROPE_COUNTRIES: dict[str, str] = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland",
    "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
    "EE": "Estonia", "ES": "Spain", "FI": "Finland", "FR": "France",
    "GB": "United Kingdom", "GR": "Greece", "HR": "Croatia", "HU": "Hungary",
    "IE": "Ireland", "IS": "Iceland", "IT": "Italy", "LI": "Liechtenstein",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta",
    "NL": "Netherlands", "NO": "Norway", "PL": "Poland", "PT": "Portugal",
    "RO": "Romania", "RS": "Serbia", "SE": "Sweden", "SI": "Slovenia",
    "SK": "Slovakia", "TR": "Turkey", "UA": "Ukraine",
}

_NAME_TO_CODE = {v.lower(): k for k, v in EUROPE_COUNTRIES.items()}
# common aliases seen in job adverts
_NAME_TO_CODE.update({
    "uk": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "wales": "GB", "czech republic": "CZ", "holland": "NL",
    "the netherlands": "NL", "türkiye": "TR",
})


def to_code(value: str) -> str:
    """Normalize a country name or code to an ISO alpha-2 code ('' if unknown)."""
    v = (value or "").strip()
    if not v:
        return ""
    if v.upper() in EUROPE_COUNTRIES:
        return v.upper()
    return _NAME_TO_CODE.get(v.lower(), "")


def is_europe(value: str) -> bool:
    """True for European country names/codes; also True for empty (unknown)
    so records without country data are not silently dropped — they are
    flagged for review instead of discarded."""
    v = (value or "").strip()
    if not v:
        return True
    return bool(to_code(v))


def country_name(code: str) -> str:
    return EUROPE_COUNTRIES.get((code or "").upper(), code or "")


def detect_country(text: str) -> str:
    """Best-effort country detection from free text; returns alpha-2 or ''."""
    low = (text or "").lower()
    for name, code in _NAME_TO_CODE.items():
        if len(name) > 3 and name in low:
            return code
    return ""
