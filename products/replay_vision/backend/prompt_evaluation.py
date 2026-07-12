"""Test a prompt suggestion before applying it: re-run the scanner with the suggested prompt against
already-rated sessions, compare each fresh output with the stored one, and persist the results on the
suggestion row."""

import uuid
import datetime as dt
from typing import Any, Literal

from django.utils import timezone

from products.replay_vision.backend.billing import observation_credits_for_model
from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion

# Each evaluated session is a full scanner run, so keep the bill bounded.
EVALUATION_SESSION_CAP = 100
# What a test run re-runs unless the caller picks a size, keeping the default spend small.
EVALUATION_SESSION_DEFAULT = 10

_EVALUATION_USAGE_NAMESPACE = uuid.UUID("8f6f5e56-9f0b-4c5a-9a3e-2b7d1c4e8a90")


def evaluation_usage_id(suggestion_id: uuid.UUID, session_id: str, started_at: str) -> uuid.UUID:
    """Deterministic receipt id per (suggestion, session, run start): a retry dedups, a re-test charges again."""
    return uuid.uuid5(_EVALUATION_USAGE_NAMESPACE, f"{suggestion_id}:{session_id}:{started_at}")


EVALUATION_SUPPORTED_TYPES = (ScannerType.MONITOR, ScannerType.CLASSIFIER)

EvaluationOutcome = Literal["kept", "regressed", "fixed", "still_wrong", "error"]


def evaluation_supported(scanner: ReplayScanner) -> bool:
    """Only scanner types with a discrete primary outcome can be diffed against ratings."""
    return scanner.scanner_type in EVALUATION_SUPPORTED_TYPES


def select_evaluation_observations(scanner: ReplayScanner, session_limit: int | None = None) -> list[ReplayObservation]:
    """Thumbs-down first (what the rewrite must fix), newest first, then thumbs-up to fill the cap.

    `session_limit` lets the caller re-run fewer sessions than the cap. It can never raise it.
    """
    cap = min(EVALUATION_SESSION_CAP, session_limit) if session_limit else EVALUATION_SESSION_CAP
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
    down = list(rated.filter(label__is_correct=False)[:cap])
    up = list(rated.filter(label__is_correct=True)[: cap - len(down)])
    return down + up


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
    """A `None` outcome is valid (e.g. a classifier with no tags). The caller records run failures as `error`."""
    changed = before != after
    if rated_correct:
        return "regressed" if changed else "kept"
    return "fixed" if changed else "still_wrong"


# Slack past the workflow execution timeout before a still-"running" evaluation is considered dead.
_EVALUATION_RUNNING_GRACE = dt.timedelta(minutes=5)


def evaluation_in_flight(evaluation: Any) -> bool:
    """True while a running evaluation's workflow can still be alive. Past the timeout nothing is left to finalize it."""
    if not isinstance(evaluation, dict) or evaluation.get("status") != "running":
        return False
    try:
        started_at = dt.datetime.fromisoformat(str(evaluation.get("started_at") or ""))
    except ValueError:
        return False
    if started_at.tzinfo is None:
        return False
    # Deferred: this business module is imported by `quota`, while importing the temporal package
    # eagerly loads the activity graph (incl. `create_observation`, which imports `quota` back).
    # A module-level import here closes that cycle; keeping it lazy breaks it.
    from products.replay_vision.backend.temporal.constants import (  # noqa: PLC0415
        EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT,
    )

    return timezone.now() - started_at < EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT + _EVALUATION_RUNNING_GRACE


def in_flight_evaluation_credits(organization_id: uuid.UUID) -> int:
    """Credits that running evaluations still plan to charge. Settled sessions hold a receipt or never charge."""
    rows = ReplayScannerPromptSuggestion.objects.filter(
        team__organization_id=organization_id, evaluation__status="running"
    ).values_list("evaluation", "scanner__model")
    total = 0
    for evaluation, model in rows:
        if not isinstance(evaluation, dict) or not evaluation_in_flight(evaluation):
            continue
        unsettled = max(0, int(evaluation.get("total") or 0) - len(evaluation.get("results") or []))
        total += unsettled * observation_credits_for_model(model or "")
    return total


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
