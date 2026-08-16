"""Profile-review gate — deterministic decision logic for how (or whether) a
candidate CV/profile should personalize a proposal.

The old behaviour hard-blocked drafting on any poor extraction with an opaque
"NEEDS_PROFILE_REVIEW blocks drafting". This module replaces that with a
structured, explainable decision the UI can render and the user can act on:

  * ``evaluate_profile_gate`` classifies extraction/review problems into
    warnings vs critical blockers, says which field/sentence/file caused each,
    and picks a safe (never destructive) default personalization mode.
  * ``resolve_personalization`` combines that gate with the user's choice to
    decide the effective mode ("full" | "safe_facts" | "none") or a hard block.
  * ``safe_profile_facts`` returns only clearly low-risk candidate facts
    (education, employment, skills, experience, publications) so uncertain or
    flagged claims never reach the proposal.

Everything here is pure/deterministic — no LLM, no network. Nothing in this
module relaxes topic-fidelity, citation, evidence, quarantine, or quality
checks; it only governs which profile text (if any) is handed to drafting.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from . import candidate_context as cc

# Personalization modes recorded on every generated proposal.
FULL = "full"            # fully personalized from the cleaned candidate facts
SAFE_FACTS = "safe_facts"  # partially personalized: low-risk facts only
NONE = "none"            # generated without any candidate personalization

# Sentences that state a clearly low-risk, verifiable candidate fact. Used to
# build the "safe facts" subset and to decide whether a flagged profile still
# has enough safe content to personalize with.
_SAFE_MARKERS = (
    "education", "degree", "bachelor", "master", "msc", "m.sc", "bsc", "b.sc",
    "phd", "ph.d", "university", "college", "institute", "graduated", "gpa",
    "cgpa", "employment", "experience", "worked", "work experience", "position",
    "role", "engineer", "developer", "analyst", "manager", "assistant",
    "officer", "director", "consultant", "skills", "proficient", "proficiency",
    "certification", "certified", "certificate", "publication", "published",
    "thesis", "dissertation", "training", "internship", "professional",
)

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_NAME_LINE = re.compile(r"^[A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+){1,3}$")
_NAME_STOP = {"curriculum", "vitae", "resume", "profile", "cv", "phd", "research",
              "proposal", "summary", "professional", "contact", "objective"}


@dataclass
class ProfileFlag:
    """One profile-review finding, in terms the UI shows directly."""
    code: str          # machine code, e.g. "too_short", "identity_conflict"
    severity: str      # "warning" | "critical"
    message: str       # what was flagged
    field: str         # which extracted field / sentence / file caused it
    consequence: str   # what will happen if the user proceeds


@dataclass
class ProfileGate:
    severity: str = "ok"            # "ok" | "warning" | "critical"
    blocking_class: str = ""        # "" | "data" (override via none) | "file" (no override)
    flags: list = field(default_factory=list)   # list[ProfileFlag]
    default_mode: str = FULL        # safe, non-destructive default
    allow_override_without_personalization: bool = True

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileGate":
        flags = [ProfileFlag(**f) for f in (d.get("flags") or [])]
        return cls(
            severity=d.get("severity", "ok"),
            blocking_class=d.get("blocking_class", ""),
            flags=flags,
            default_mode=d.get("default_mode", FULL),
            allow_override_without_personalization=bool(
                d.get("allow_override_without_personalization", True)),
        )


def extracted_applicant_name(profile_text: str) -> str:
    """Best-effort candidate name from the top of the CV (a line of 2–4
    capitalised name tokens). Empty when nothing name-like is found."""
    for raw in (profile_text or "").splitlines()[:12]:
        line = raw.strip().strip("#").strip()
        if not line or any(w in line.lower() for w in _NAME_STOP):
            continue
        if _NAME_LINE.match(line) or (line.isupper() and 2 <= len(line.split()) <= 4
                                      and line.replace(" ", "").isalpha()):
            return " ".join(line.split())
    return ""


def _name_tokens(name: str) -> set[str]:
    return {t for t in re.findall(r"[a-z]+", (name or "").lower()) if len(t) > 1}


def names_conflict(selected: str, extracted: str) -> bool:
    """True when both names are present and share NO name token — a strong
    signal the uploaded CV belongs to a different person than selected."""
    a, b = _name_tokens(selected), _name_tokens(extracted)
    if not a or not b:
        return False
    return a.isdisjoint(b)


def safe_profile_facts(profile_text: str) -> str:
    """Only clearly low-risk candidate facts (education, employment, skills,
    experience, publications). Built from the already-cleaned candidate context
    (proposed-direction sentences removed), then filtered to sentences that
    carry a safe marker. Uncertain / unmarked sentences are dropped so they
    cannot reach the proposal."""
    cleaned = cc.clean_candidate_context(profile_text or "")
    kept = [s.strip() for s in _SENT_SPLIT.split(cleaned)
            if s.strip() and any(m in s.lower() for m in _SAFE_MARKERS)]
    return " ".join(kept).strip()


def _classify_reason(reason: str, source_name: str) -> ProfileFlag:
    """Map an intake reason string to a structured flag."""
    low = reason.lower()
    if low.startswith("profile file not found"):
        return ProfileFlag("file_not_found", "critical", reason, source_name,
                            "Blocked: the CV cannot be read. Remove the file or "
                            "upload a readable one to continue.")
    if low.startswith("unsupported profile format"):
        return ProfileFlag("unsupported_format", "critical", reason, source_name,
                            "Blocked: this file type cannot be parsed. Upload a "
                            "PDF, DOCX, TXT or MD, or remove the file.")
    if low.startswith("extraction failed"):
        return ProfileFlag("extraction_failed", "critical", reason, source_name,
                            "Blocked: the file appears corrupt/unreadable. Replace "
                            "it with a readable CV, or remove it, to continue.")
    if "replacement characters" in low:
        return ProfileFlag("garbled", "critical", reason, source_name,
                            "Blocked: the extracted text is garbled (likely a "
                            "corrupt or scanned-image CV). Replace or remove it.")
    if low.startswith("extracted profile too short"):
        return ProfileFlag("too_short", "warning", reason, "whole document",
                            "The profile is too thin to personalize safely; "
                            "generation proceeds using safe facts or none.")
    if "no recognizable sections" in low:
        return ProfileFlag("no_structure", "warning", reason, "whole document",
                            "The profile has little usable structure; only "
                            "clearly safe facts will be used, if any.")
    # Unknown reason -> treat conservatively as a warning, still surfaced.
    return ProfileFlag("profile_warning", "warning", reason, "whole document",
                       "Only clearly safe facts will be used, if any.")


def evaluate_profile_gate(*, reasons: list[str], profile_text: str,
                          applicant_name: str | None,
                          profile_provided: bool,
                          source_name: str = "the uploaded file") -> ProfileGate:
    """Classify the profile situation into a structured, explainable gate."""
    if not profile_provided:
        # No CV supplied — normal, not flagged. Nothing to personalize with.
        return ProfileGate(severity="ok", blocking_class="", flags=[],
                            default_mode=NONE,
                            allow_override_without_personalization=True)

    flags: list[ProfileFlag] = []
    crit_file = False
    for r in (reasons or []):
        f = _classify_reason(r, source_name)
        if f.severity == "critical":
            crit_file = True
        flags.append(f)

    crit_data = False
    if applicant_name and profile_text:
        extracted = extracted_applicant_name(profile_text)
        if extracted and names_conflict(applicant_name, extracted):
            crit_data = True
            flags.append(ProfileFlag(
                "identity_conflict", "critical",
                "extracted applicant name does not match the selected applicant",
                f"applicant name — CV: '{extracted}' vs selected: '{applicant_name}'",
                "Blocked to avoid inserting the wrong person's details. You may "
                "still generate WITHOUT candidate personalization."))

    # File-level critical: hard block, override not allowed.
    if crit_file:
        return ProfileGate(severity="critical", blocking_class="file", flags=flags,
                           default_mode=NONE,
                           allow_override_without_personalization=False)
    # Data-level critical (identity/unsafe data): blocked, override -> none.
    if crit_data:
        return ProfileGate(severity="critical", blocking_class="data", flags=flags,
                           default_mode=NONE,
                           allow_override_without_personalization=True)
    # Warnings only: proceed safely by default, user may still choose.
    if flags:
        safe_available = len(safe_profile_facts(profile_text)) >= 80
        return ProfileGate(severity="warning", blocking_class="", flags=flags,
                           default_mode=(SAFE_FACTS if safe_available else NONE),
                           allow_override_without_personalization=True)
    # Clean profile.
    return ProfileGate(severity="ok", blocking_class="", flags=[],
                       default_mode=FULL,
                       allow_override_without_personalization=True)


# Result of resolving the gate against the user's requested handling.
BLOCK = "BLOCK"          # hard block (file critical, or data critical w/o override)
STOP = "STOP"            # user explicitly chose to stop and review


def resolve_personalization(gate: ProfileGate, requested: str) -> tuple[str, str]:
    """Return (outcome, detail). ``outcome`` is a personalization mode
    (full/safe_facts/none) to proceed with, or BLOCK / STOP. ``requested`` is
    one of auto/full/safe_facts/none/stop (the user's choice)."""
    requested = (requested or "auto").lower()

    # File-level critical always blocks — even "none" cannot rescue a corrupt file.
    if gate.blocking_class == "file":
        return BLOCK, _block_detail(gate)

    if requested == "stop":
        return STOP, "User chose to stop and review the profile before drafting."

    # Data-level critical (identity conflict): only "none" may proceed.
    if gate.blocking_class == "data":
        if requested == NONE:
            return NONE, ""
        return BLOCK, _block_detail(gate)

    # Warnings or clean profile.
    if requested == "auto":
        return gate.default_mode, ""
    if requested in (FULL, SAFE_FACTS, NONE):
        # Never let "full" override a warning — that could insert uncertain facts.
        if gate.severity == "warning" and requested == FULL:
            return gate.default_mode, ""
        return requested, ""
    return gate.default_mode, ""


def _block_detail(gate: ProfileGate) -> str:
    """A precise, user-facing block reason — never a generic 'blocks drafting'."""
    crit = [f for f in gate.flags if f.severity == "critical"]
    parts = [f"{f.message} ({f.field})" for f in crit] or ["profile review failed"]
    tail = ("" if gate.blocking_class == "file"
            else " — choose 'Generate without candidate personalization' to proceed.")
    return "Profile blocked: " + "; ".join(parts) + tail
