"""Marks provably-orphaned pending/running observations as failed so they stop blocking re-scans and eating quota.

The same pass reaps prompt-suggestion evaluations stuck in `running`: the workflow swallows finalize
failures, so a terminated or timed-out run leaves the row claiming to be in flight forever.
"""

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from temporalio import activity
from temporalio.client import Client

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion
from products.replay_vision.backend.prompt_evaluation import (
    EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT,
    summarize_results,
)
from products.replay_vision.backend.temporal.activities.observation_state import mark_observation_terminal
from products.replay_vision.backend.temporal.activities.reaping import classify_stale_rows
from products.replay_vision.backend.temporal.constants import (
    OBSERVATION_ORPHAN_CUTOFF,
    REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE,
    build_evaluate_prompt_suggestion_workflow_id,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.errors import FailureKind
from products.replay_vision.backend.temporal.metrics import record_failure_kind

logger = structlog.get_logger(__name__)

_LIVE_STATUSES = (ObservationStatus.PENDING, ObservationStatus.RUNNING)
_ORPHANED_ERROR_REASON = f"{FailureKind.ORPHANED.value}:The analysis stopped without recording an outcome."
# Evaluations whose stamp predates the workflow's own execution timeout can no longer be live.
_EVALUATION_ORPHAN_CUTOFF = EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT * 2
# One pass reaps at most this many; the rest drain on later reconciler ticks.
_EVALUATION_BATCH_SIZE = 100


def _list_stale_observations() -> list[dict[str, Any]]:
    cutoff = datetime.now(UTC) - OBSERVATION_ORPHAN_CUTOFF
    rows = (
        ReplayObservation.objects.filter(status__in=_LIVE_STATUSES, created_at__lt=cutoff)
        .order_by("created_at")
        .values("id", "workflow_id", "scanner_snapshot")[:REAP_ORPHANED_OBSERVATIONS_BATCH_SIZE]
    )
    # cast: django-stubs types `.values()` rows as a TypedDict, which mypy won't widen to dict[str, Any].
    return cast(list[dict[str, Any]], list(rows))


def _evaluation_stamp_is_stale(evaluation: dict[str, Any], cutoff: datetime) -> bool:
    """A stamp that is unparseable or naive can never age out on its own, so it counts as stale."""
    try:
        started_at = datetime.fromisoformat(str(evaluation.get("started_at") or ""))
    except ValueError:
        return True
    return started_at.tzinfo is None or started_at < cutoff


def _list_stale_evaluations() -> list[dict[str, Any]]:
    """Suggestions whose running evaluation predates the cutoff, shaped for `classify_stale_rows`."""
    cutoff = timezone.now() - _EVALUATION_ORPHAN_CUTOFF
    rows = (
        ReplayScannerPromptSuggestion.objects.filter(evaluation__status="running")
        .order_by("created_at")
        .values("id", "evaluation")[:_EVALUATION_BATCH_SIZE]
    )
    return [
        {"id": row["id"], "workflow_id": build_evaluate_prompt_suggestion_workflow_id(row["id"])}
        for row in rows
        if isinstance(row["evaluation"], dict) and _evaluation_stamp_is_stale(row["evaluation"], cutoff)
    ]


def _mark_orphaned(observation_id: UUID, scanner_type: str) -> bool:
    return mark_observation_terminal(
        observation_id=observation_id,
        status=ObservationStatus.FAILED,
        error_reason=_ORPHANED_ERROR_REASON,
        scanner_type=scanner_type,
        valid_kinds={FailureKind.ORPHANED.value},
        count_kind=lambda kind: record_failure_kind(kind, scanner_type),
    )


def _fail_evaluation(suggestion_id: UUID) -> bool:
    """Settle a stuck evaluation as failed. Mirrors `finalize_evaluation_activity`'s write."""
    with transaction.atomic():
        suggestion = ReplayScannerPromptSuggestion.objects.select_for_update().filter(pk=suggestion_id).first()
        if suggestion is None or not isinstance(suggestion.evaluation, dict):
            return False
        # A run that finalized between the listing and this write must not be clobbered.
        if suggestion.evaluation.get("status") != "running":
            return False
        results = suggestion.evaluation.get("results", [])
        suggestion.evaluation = {
            **suggestion.evaluation,
            "status": "failed",
            "finished_at": timezone.now().isoformat(),
            "summary": summarize_results(results),
        }
        suggestion.save(update_fields=["evaluation"])
    return True


async def _reap_observations(temporal: Client, rows: list[dict[str, Any]]) -> int:
    reapable, skipped_open, skipped_temporal_error = await classify_stale_rows(
        temporal, rows, workflow_id_key="workflow_id"
    )
    activity.heartbeat({"phase": "observations_described", "reapable": len(reapable)})
    reaped = 0
    for row in reapable:
        snapshot = row["scanner_snapshot"] or {}
        scanner_type = snapshot.get("scanner_type") or "unknown"
        if await database_sync_to_async(_mark_orphaned, thread_sensitive=False)(row["id"], scanner_type):
            reaped += 1
        # The SDK throttles the RPCs, so per-row is cheap.
        activity.heartbeat({"phase": "observations_reaping", "reaped": reaped})
    logger.info(
        "replay_vision.reap_orphaned_observations",
        scanned=len(rows),
        reaped=reaped,
        skipped_open=skipped_open,
        skipped_temporal_error=skipped_temporal_error,
    )
    return reaped


async def _reap_evaluations(temporal: Client, rows: list[dict[str, Any]]) -> int:
    reapable, _, _ = await classify_stale_rows(temporal, rows, workflow_id_key="workflow_id")
    activity.heartbeat({"phase": "evaluations_described", "reapable": len(reapable)})
    reaped = 0
    for row in reapable:
        if await database_sync_to_async(_fail_evaluation, thread_sensitive=False)(row["id"]):
            reaped += 1
        activity.heartbeat({"phase": "evaluations_reaping", "reaped": reaped})
    logger.info("replay_vision.reap_stuck_evaluations", scanned=len(rows), reaped=reaped)
    return reaped


@activity.defn
@track_activity()
async def reap_orphaned_observations_activity() -> int:
    """Fail pending/running rows past the orphan cutoff whose workflow is no longer open, and settle
    prompt-suggestion evaluations stuck in `running`; returns the total count reaped.

    The describe check protects rows reclaimed by a live re-trigger of the same deterministic workflow id.
    """
    rows = await database_sync_to_async(_list_stale_observations, thread_sensitive=False)()
    evaluations = await database_sync_to_async(_list_stale_evaluations, thread_sensitive=False)()
    if not rows and not evaluations:
        return 0
    activity.heartbeat({"phase": "listed", "observations": len(rows), "evaluations": len(evaluations)})
    temporal = await async_connect()
    return await _reap_observations(temporal, rows) + await _reap_evaluations(temporal, evaluations)
