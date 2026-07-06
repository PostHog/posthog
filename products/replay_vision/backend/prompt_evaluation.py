"""Test a prompt suggestion before applying it: re-run the scanner with the suggested prompt against
already-rated sessions and compare each fresh output with the stored one.

The rated set doubles as a labeled test set: a changed output is a likely regression on a thumbs-up
session and a likely fix on a thumbs-down one. Results persist on the suggestion row so the Quality
tab can show them without re-running.
"""

from typing import Any, Literal

from django.utils import timezone

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType

# Each evaluated session is a full scanner run (video upload + LLM conversation), so keep the bill bounded.
EVALUATION_SESSION_CAP = 10

EVALUATION_SUPPORTED_TYPES = (ScannerType.MONITOR, ScannerType.CLASSIFIER)

EvaluationOutcome = Literal["kept", "regressed", "fixed", "still_wrong", "error"]


def evaluation_supported(scanner: ReplayScanner) -> bool:
    """Only scanner types with a discrete primary outcome can be diffed against ratings."""
    return scanner.scanner_type in EVALUATION_SUPPORTED_TYPES


def select_evaluation_observations(scanner: ReplayScanner) -> list[ReplayObservation]:
    """Thumbs-down first (what the rewrite must fix), newest first, then thumbs-up to fill the cap."""
    rated = (
        ReplayObservation.objects.filter(
            team_id=scanner.team_id,
            scanner_id=scanner.id,
            status=ObservationStatus.SUCCEEDED,
            label__isnull=False,
        )
        .select_related("label")
        .order_by("-created_at")
    )
    down = [o for o in rated if not o.label.is_correct]  # type: ignore[attr-defined]
    up = [o for o in rated if o.label.is_correct]  # type: ignore[attr-defined]
    return (down + up)[:EVALUATION_SESSION_CAP]


def primary_outcome(model_output: dict[str, Any] | None) -> str | None:
    """The discrete outcome string used for before/after comparison."""
    output = model_output or {}
    verdict = output.get("verdict")
    if isinstance(verdict, str) and verdict:
        return f"Verdict: {verdict.strip().lower()}"
    tags = sorted(t.strip().lower() for t in (output.get("tags") or []) if isinstance(t, str) and t.strip())
    if tags:
        return f"Tags: {', '.join(tags)}"
    return None


def classify_outcome(rated_correct: bool, before: str | None, after: str | None) -> EvaluationOutcome:
    if after is None:
        return "error"
    changed = before != after
    if rated_correct:
        return "regressed" if changed else "kept"
    return "fixed" if changed else "still_wrong"


def build_running_evaluation(total: int, labels_fingerprint: str) -> dict[str, Any]:
    return {
        "status": "running",
        "started_at": timezone.now().isoformat(),
        "finished_at": None,
        "total": total,
        "labels_fingerprint": labels_fingerprint,
        "results": [],
        "summary": None,
    }


def summarize_results(results: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"kept": 0, "regressed": 0, "fixed": 0, "still_wrong": 0, "errors": 0}
    for result in results:
        outcome = result.get("outcome")
        if outcome == "error":
            summary["errors"] += 1
        elif outcome in summary:
            summary[outcome] += 1
    return summary
