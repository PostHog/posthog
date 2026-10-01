"""Activities for the scheduled experiment recalculation workflow.

Each one wraps `scheduled_recalculation_logic` and reports its outcome to product analytics.
Every activity is fire and forget: a failure skips one experiment and never stops the batch,
because the recalculation workflow it starts owns its own retries and error reporting.
"""

from typing import Any

from django.db import close_old_connections

import structlog
import posthoganalytics
import temporalio.activity

from posthog.event_usage import groups
from posthog.sync import database_sync_to_async_pool

from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.recalculation import request_recalculation, start_metrics_recalculation_workflow
from products.experiments.backend.temporal.models import ScheduledRecalculationStartResult
from products.experiments.backend.temporal.scheduled_recalculation_logic import (
    MIN_TOTAL_EXPOSURES,
    SKIP_ACTIVE_RUN,
    SKIP_EXPOSURE_QUERY_FAILED,
    SKIP_INSUFFICIENT_EXPOSURES,
    ScheduledRecalculationCandidate,
    count_total_exposures,
    find_scheduled_recalculation_candidates,
    recent_recalculation_skip,
)

logger = structlog.get_logger(__name__)

STARTED_EVENT = "experiment scheduled recalculation started"
SKIPPED_EVENT = "experiment scheduled recalculation skipped"


def _capture(experiment: Experiment, event: str, properties: dict[str, Any]) -> None:
    """Global client, not ph_scoped_capture: the worker is long lived, so its background flush
    runs, while a scoped client's synchronous shutdown stalls the activity for about twice the
    flush interval. Telemetry must never fail an activity, so every error is swallowed."""
    try:
        team = experiment.team
        distinct_id = (
            experiment.created_by.distinct_id
            if experiment.created_by and experiment.created_by.distinct_id
            else f"team_{team.id}"
        )
        posthoganalytics.capture(
            distinct_id=distinct_id,
            event=event,
            properties={"experiment_id": experiment.id, "team_id": team.id, **properties},
            groups=groups(organization=team.organization, team=team),
        )
    except Exception:
        logger.warning("scheduled_recalculation_capture_failed", event=event, experiment_id=experiment.id)


def capture_skip(experiment: Experiment, hour: int, reason: str, detail: dict[str, Any]) -> None:
    _capture(experiment, SKIPPED_EVENT, {"hour": hour, "reason": reason, **detail})


def capture_started(experiment: Experiment, hour: int, recalculation_id: str) -> None:
    _capture(experiment, STARTED_EVENT, {"hour": hour, "recalculation_id": recalculation_id})


@database_sync_to_async_pool
def _discover_scheduled_recalculation_candidates_sync(hour: int) -> list[ScheduledRecalculationCandidate]:
    close_old_connections()
    return find_scheduled_recalculation_candidates(hour)


@temporalio.activity.defn
async def discover_scheduled_recalculation_candidates(hour: int) -> list[ScheduledRecalculationCandidate]:
    """Experiments eligible for a scheduled recalculation at this hour, before the exposure gate."""
    return await _discover_scheduled_recalculation_candidates_sync(hour)


@database_sync_to_async_pool
def _check_experiment_exposures_sync(experiment_id: int, hour: int) -> bool:
    close_old_connections()
    experiment = Experiment.objects.filter(id=experiment_id, deleted=False).first()
    if experiment is None:
        return False
    try:
        total = count_total_exposures(experiment)
    except Exception as error:
        capture_skip(experiment, hour, reason=SKIP_EXPOSURE_QUERY_FAILED, detail={"error_message": str(error)[:500]})
        logger.warning("scheduled_recalculation_exposure_query_failed", experiment_id=experiment_id)
        return False
    if total < MIN_TOTAL_EXPOSURES:
        capture_skip(experiment, hour, reason=SKIP_INSUFFICIENT_EXPOSURES, detail={"total_exposures": total})
        return False
    return True


@temporalio.activity.defn
async def check_experiment_exposures(experiment_id: int, hour: int) -> bool:
    """Whether one experiment has enough exposures to be worth recalculating.

    A query failure counts as a skip: an experiment whose exposure query fails would fail its
    metric queries too, so starting a run would only burn the cluster.
    """
    return await _check_experiment_exposures_sync(experiment_id, hour)


@database_sync_to_async_pool
def _start_scheduled_recalculation_sync(experiment_id: int, hour: int) -> ScheduledRecalculationStartResult:
    close_old_connections()
    # Re-check RUNNING, not just deleted: discovery ran before the exposure query, and an
    # experiment stopped in between should not get a scheduled run.
    experiment = (
        Experiment.objects.filter(id=experiment_id, deleted=False, status=Experiment.Status.RUNNING)
        .select_related("team")
        .first()
    )
    if experiment is None:
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=False)

    skip = recent_recalculation_skip(experiment, experiment.team_id)
    if skip is not None:
        capture_skip(experiment, hour, reason=skip.reason, detail=dict(skip.detail))
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=False, skip_reason=skip.reason)

    try:
        payload = request_recalculation(experiment, None, ExperimentMetricsRecalculation.Trigger.STALE_REFRESH)
    except Exception:
        logger.warning("scheduled_recalculation_request_failed", experiment_id=experiment_id, exc_info=True)
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=False)

    # The pre-check above and this create are separate, unsynchronized reads: a run can start
    # between them. request_recalculation's own is_existing flag closes that window instead of
    # relying on the two staying in step.
    if payload.get("is_existing"):
        return ScheduledRecalculationStartResult(
            experiment_id=experiment_id, started=False, skip_reason=SKIP_ACTIVE_RUN
        )

    recalculation_id = str(payload["id"])
    try:
        start_metrics_recalculation_workflow(
            recalculation_id,
            team_id=experiment.team_id,
            organization_id=str(experiment.team.organization_id),
        )
    except Exception:
        # start_metrics_recalculation_workflow rolls the row back to FAILED itself, so an orphaned
        # PENDING row cannot look active to every later scheduled run.
        logger.warning(
            "scheduled_recalculation_dispatch_failed",
            experiment_id=experiment_id,
            recalculation_id=recalculation_id,
            exc_info=True,
        )
        return ScheduledRecalculationStartResult(experiment_id=experiment_id, started=False)

    capture_started(experiment, hour, recalculation_id)
    return ScheduledRecalculationStartResult(
        experiment_id=experiment_id, started=True, recalculation_id=recalculation_id
    )


@temporalio.activity.defn
async def start_scheduled_recalculation(experiment_id: int, hour: int) -> ScheduledRecalculationStartResult:
    """Create the recalculation row and dispatch its workflow, unless a recent or active run exists."""
    return await _start_scheduled_recalculation_sync(experiment_id, hour)
