"""Marks provably-orphaned pending/running observations as failed so they stop blocking re-scans and eating quota.

The same pass reaps prompt-suggestion evaluations stuck in `running`: the workflow swallows finalize
failures, so a terminated or timed-out run leaves the row claiming to be in flight forever.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from django.db import transaction
from django.utils import timezone

import structlog
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect

from products.replay_vision.backend.models.replay_observation import ObservationStatus, ReplayObservation
from products.replay_vision.backend.models.replay_scanner_prompt_suggestion import ReplayScannerPromptSuggestion
from products.replay_vision.backend.prompt_evaluation import (
    EVALUATE_PROMPT_SUGGESTION_EXECUTION_TIMEOUT,
    summarize_results,
)
from products.replay_vision.backend.temporal.activities.observation_state import mark_observation_terminal
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
# Describes are Temporal-API round trips; running them a few at a time keeps a 500-row pass inside the
# activity's budget without hammering the service.
_DESCRIBE_CONCURRENCY = 20
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


def _list_stale_evaluations() -> list[UUID]:
    cutoff = timezone.now() - _EVALUATION_ORPHAN_CUTOFF
    rows = (
        ReplayScannerPromptSuggestion.objects.filter(evaluation__status="running")
        .order_by("created_at")
        .values("id", "evaluation")[:_EVALUATION_BATCH_SIZE]
    )
    stale: list[UUID] = []
    for row in rows:
        evaluation = row["evaluation"]
        if not isinstance(evaluation, dict):
            continue
        try:
            started_at = datetime.fromisoformat(str(evaluation.get("started_at") or ""))
        except ValueError:
            # An unparseable stamp can never age out on its own, so treat it as stale.
            stale.append(row["id"])
            continue
        if started_at.tzinfo is not None and started_at < cutoff:
            stale.append(row["id"])
    return stale


async def _workflow_is_open(temporal: Client, workflow_id: str) -> bool | None:
    """Whether the latest run of `workflow_id` is still open; `None` when Temporal couldn't answer."""
    try:
        desc = await temporal.get_workflow_handle(workflow_id).describe()
    except RPCError as e:
        if e.status == RPCStatusCode.NOT_FOUND:
            return False
        return None
    except Exception:
        return None
    return desc.status == WorkflowExecutionStatus.RUNNING


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
    activity.heartbeat({"phase": "observations_listed", "scanned": len(rows)})
    describe_sem = asyncio.Semaphore(_DESCRIBE_CONCURRENCY)

    async def _still_open(row: dict[str, Any]) -> bool | None:
        if not row["workflow_id"]:
            return False
        async with describe_sem:
            return await _workflow_is_open(temporal, row["workflow_id"])

    openness = await asyncio.gather(*(_still_open(row) for row in rows))
    activity.heartbeat({"phase": "observations_described", "described": len(openness)})

    reaped = 0
    skipped_open = 0
    skipped_temporal_error = 0
    for row, is_open in zip(rows, openness):
        if is_open:
            skipped_open += 1
            continue
        if is_open is None:
            skipped_temporal_error += 1  # Can't prove it's closed — leave it for the next tick.
            continue
        snapshot = row["scanner_snapshot"] or {}
        scanner_type = snapshot.get("scanner_type") or "unknown"
        if await database_sync_to_async(_mark_orphaned, thread_sensitive=False)(row["id"], scanner_type):
            reaped += 1
    logger.info(
        "replay_vision.reap_orphaned_observations",
        scanned=len(rows),
        reaped=reaped,
        skipped_open=skipped_open,
        skipped_temporal_error=skipped_temporal_error,
    )
    return reaped


async def _reap_evaluations(temporal: Client, suggestion_ids: list[UUID]) -> int:
    activity.heartbeat({"phase": "evaluations_listed", "scanned": len(suggestion_ids)})
    describe_sem = asyncio.Semaphore(_DESCRIBE_CONCURRENCY)

    async def _still_open(suggestion_id: UUID) -> bool | None:
        async with describe_sem:
            return await _workflow_is_open(temporal, build_evaluate_prompt_suggestion_workflow_id(suggestion_id))

    openness = await asyncio.gather(*(_still_open(sid) for sid in suggestion_ids))
    reaped = 0
    for suggestion_id, is_open in zip(suggestion_ids, openness):
        # Only settle rows whose workflow is provably gone; a slow-but-live run keeps reporting progress.
        if is_open is not False:
            continue
        if await database_sync_to_async(_fail_evaluation, thread_sensitive=False)(suggestion_id):
            reaped += 1
    logger.info("replay_vision.reap_stuck_evaluations", scanned=len(suggestion_ids), reaped=reaped)
    return reaped


@activity.defn
@track_activity()
async def reap_orphaned_observations_activity() -> int:
    """Fail pending/running rows past the orphan cutoff whose workflow is no longer open, and settle
    prompt-suggestion evaluations stuck in `running`; returns the total count reaped.

    The describe check protects rows reclaimed by a live re-trigger of the same deterministic workflow id.
    """
    rows = await database_sync_to_async(_list_stale_observations, thread_sensitive=False)()
    suggestion_ids = await database_sync_to_async(_list_stale_evaluations, thread_sensitive=False)()
    if not rows and not suggestion_ids:
        return 0
    temporal = await async_connect()
    reaped = await _reap_observations(temporal, rows) if rows else 0
    return reaped + (await _reap_evaluations(temporal, suggestion_ids) if suggestion_ids else 0)
