"""``run_log.json`` management and the resumability rule.

Resumability rule (Phase 0):
    A stage is skipped ONLY when
      1. all of its required output artifacts exist on disk, AND
      2. run_log marks that stage status == "SUCCESS".
    Failed, partial, missing-status, or invalid artifacts must be rerun.
    ``--force`` reruns everything for the selected topic/client.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SUCCESS = "SUCCESS"
FAILED = "FAILED"
PARTIAL = "PARTIAL"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunLog:
    def __init__(self, path: str | Path, topic_id: str = ""):
        self.path = Path(path)
        self.data: dict = {
            "topic_id": topic_id,
            "created": _now(),
            "updated": _now(),
            "preflight": {},
            "stages": {},
            "status": "IN_PROGRESS",
            "failure": None,
            "approved": False,
        }
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except (json.JSONDecodeError, OSError):
                # A corrupt run_log means "no trustworthy status" -> rerun all.
                pass

    # ---- persistence -------------------------------------------------
    def save(self) -> None:
        self.data["updated"] = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    # ---- stage bookkeeping ------------------------------------------
    def stage_status(self, stage: str) -> str | None:
        return (self.data["stages"].get(stage) or {}).get("status")

    def mark(self, stage: str, status: str, detail: str = "", **extra) -> None:
        entry = {"status": status, "ts": _now(), "detail": detail}
        entry.update(extra)
        self.data["stages"][stage] = entry
        self.save()

    def mark_success(self, stage: str, detail: str = "", **extra) -> None:
        self.mark(stage, SUCCESS, detail, **extra)

    def mark_failed(self, stage: str, detail: str = "", **extra) -> None:
        self.mark(stage, FAILED, detail, **extra)
        self.data["status"] = "FAILED"
        self.data["failure"] = {"stage": stage, "reason": detail}
        self.save()

    def set_preflight(self, results: dict) -> None:
        self.data["preflight"] = results
        self.save()

    def set_status(self, status: str) -> None:
        self.data["status"] = status
        self.save()

    def approve(self) -> None:
        self.data["approved"] = True
        self.data["status"] = "FINAL"
        self.data["approved_at"] = _now()
        self.save()

    # ---- resumability -----------------------------------------------
    def can_skip(self, stage: str, artifacts: list[Path], force: bool = False) -> bool:
        """True only if stage==SUCCESS and every artifact exists (and not forced)."""
        if force:
            return False
        if self.stage_status(stage) != SUCCESS:
            return False
        return all(Path(a).exists() for a in artifacts)
