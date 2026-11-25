"""Run the Trino compile check for one team in batches, and report each row as a PostHog event.

Each batch runs in its own Celery task and enqueues the next batch with the ids that are still to check, so a
deploy that replaces the worker loses at most the batch in progress, and the broker delivers that batch again.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

import structlog

from posthog.models import Team
from posthog.ph_client import ph_scoped_capture
from posthog.utils import get_instance_region

from products.managed_warehouse.backend.presentation import hogtower
from products.managed_warehouse.backend.tasks import run_trino_compile_check_task
from products.managed_warehouse.backend.trino_compile_check import (
    check_trino_compile,
    trino_compile_check_saved_query_ids,
)

logger = structlog.get_logger(__name__)

RESULT_EVENT = "trino_compile_check_result"
COMPLETED_EVENT = "trino_compile_check_completed"
HOGTOWER_NOT_CONFIGURED = "hogtower_not_configured"
# An explain check takes seconds per model, so a batch of 50 runs for minutes. That keeps a batch well inside
# the time between deploys and inside the broker's visibility timeout, after which Redis delivers an unacked
# task again while it still runs.
BATCH_SIZE = 50
# Kombu's default policy gives up after three retries within a second. This one keeps retrying a broker
# that is unavailable for about three minutes before the hand-off fails.
HAND_OFF_RETRY_POLICY = {"max_retries": 10, "interval_start": 1, "interval_step": 5, "interval_max": 30}


def is_control_plane_configured() -> bool:
    return hogtower.is_configured()


def start_trino_compile_check(team_id: int, *, explain: bool, limit: int | None = None) -> str:
    run_id = str(uuid.uuid4())
    saved_query_ids = trino_compile_check_saved_query_ids(team_id, limit=limit)
    run_trino_compile_check_task.delay(
        team_id=team_id, run_id=run_id, explain=explain, limit=limit, saved_query_ids=saved_query_ids
    )
    return run_id


def run_trino_compile_check(
    team_id: int,
    *,
    run_id: str,
    explain: bool,
    limit: int | None = None,
    saved_query_ids: Sequence[str] | None = None,
    batch_index: int = 0,
    results: Mapping[str, str | None] | None = None,
) -> None:
    """Check one batch of a run, then enqueue the next batch or, after the last one, emit the completed event.

    The first batch resolves the ordered ids to check from ``saved_query_ids`` and ``limit``. A later batch gets
    the ids still to check in ``saved_query_ids``, and ``results`` maps each id an earlier batch checked to its
    error code, or to None when it passed. The results are keyed by id so that a model counts once in the totals,
    also when a redelivered batch checks it again.
    """
    team = Team.objects.get(pk=team_id)
    run_properties = {
        "run_id": run_id,
        "team_id": team_id,
        "organization_id": str(team.organization_id),
        "explain": explain,
        "$process_person_profile": False,
    }
    results = dict(results or {})
    pending: list[str] = []
    try:
        with ph_scoped_capture(event_region=get_instance_region()) as capture:

            def emit(event: str, properties: dict[str, Any]) -> None:
                capture(distinct_id=run_id, event=event, properties={**run_properties, **properties})

            if not is_control_plane_configured():
                logger.error("trino_compile_check_hogtower_not_configured", run_id=run_id, team_id=team_id)
                emit(COMPLETED_EVENT, _completed_properties(results, batch_index, {"error": HOGTOWER_NOT_CONFIGURED}))
                return

            if batch_index == 0:
                saved_query_ids = trino_compile_check_saved_query_ids(
                    team_id, saved_query_ids=saved_query_ids, limit=limit
                )
            pending = list(saved_query_ids or ())
            for row in check_trino_compile(team, saved_query_ids=pending[:BATCH_SIZE], explain=explain):
                results[row.saved_query_id] = row.error_code
                emit(RESULT_EVENT, row.to_json())
            if len(pending) <= BATCH_SIZE:
                emit(COMPLETED_EVENT, _completed_properties(results, batch_index, {}))
                return

        # The next batch is enqueued after the capture block has flushed this batch's rows. A worker that dies
        # before this call loses no rows, because the broker delivers this batch again.
        run_trino_compile_check_task.apply_async(
            kwargs={
                "team_id": team_id,
                "run_id": run_id,
                "explain": explain,
                "saved_query_ids": pending[BATCH_SIZE:],
                "batch_index": batch_index + 1,
                "results": results,
            },
            retry=True,
            retry_policy=HAND_OFF_RETRY_POLICY,
        )
    except Exception as error:
        # One handler covers the checks, the flush on exit of the capture block and the hand-off. Celery acks a
        # task that raises, so without this event no later task checks the unchecked ids. A soft time limit that
        # lands in the flush at the end of the last batch can add an error event next to the normal one.
        logger.exception("trino_compile_check_run_failed", run_id=run_id, team_id=team_id, batch_index=batch_index)
        unchecked = sum(saved_query_id not in results for saved_query_id in pending)
        failure = {"error": type(error).__name__, "message": str(error)[:300], "unchecked": unchecked}
        with ph_scoped_capture(event_region=get_instance_region()) as capture:
            capture(
                distinct_id=run_id,
                event=COMPLETED_EVENT,
                properties={**run_properties, **_completed_properties(results, batch_index, failure)},
            )
        raise


def _completed_properties(
    results: Mapping[str, str | None], batch_index: int, properties: dict[str, Any]
) -> dict[str, Any]:
    return {**_summary(results), "batches": batch_index + 1, **properties}


def _summary(results: Mapping[str, str | None]) -> dict[str, Any]:
    error_counts = Counter(code for code in results.values() if code is not None)
    return {
        "ok": len(results) - error_counts.total(),
        "total": len(results),
        "error_counts": dict(error_counts.most_common()),
    }
