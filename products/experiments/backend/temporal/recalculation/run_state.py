"""Reads and state checks on a metrics recalculation row, shared by the recalculation activities."""

import dataclasses
from datetime import datetime

from temporalio.exceptions import ApplicationError

from posthog.temporal.common.errors import NonReportableApplicationError

from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation

RECALCULATION_PAUSED_ERROR_TYPE = "recalculation_paused"


@dataclasses.dataclass(frozen=True)
class _RecalcState:
    """The recalc row fields the activities cross-check their inputs against.

    Loaded once at the top of each activity via a single unscoped SELECT — same query count as just reading
    team_id, but the extra columns let the calculate activity assert its (experiment_id, metric_uuid, query_to)
    inputs match the row state instead of trusting whatever the workflow passed.
    """

    team_id: int
    experiment_id: int
    metric_uuids: list[str]
    query_to: datetime | None
    trigger: str | None


def _get_recalc_state(recalculation_id: str) -> _RecalcState:
    """Resolve the recalc row's identifying fields without entering scope yet (chicken-and-egg)."""
    row = (
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(id=recalculation_id)
        .values("team_id", "experiment_id", "metric_uuids", "query_to", "trigger")
        .first()
    )
    if row is None:
        # Deterministic: the row's not coming back (bogus id, manual delete, cascade from team/experiment).
        # Non-retryable so Temporal terminates promptly instead of burning retries on each activity.
        raise ApplicationError(
            f"ExperimentMetricsRecalculation {recalculation_id} not found",
            type="recalculation_not_found",
            non_retryable=True,
        )
    return _RecalcState(
        team_id=row["team_id"],
        experiment_id=row["experiment_id"],
        metric_uuids=row["metric_uuids"] or [],
        query_to=row["query_to"],
        trigger=row["trigger"],
    )


def _fail_pending_run(recalculation_id: str) -> bool:
    # Only a never-started run fails, so calcs in flight finish; an empty completed_at keeps the latest results.
    return (
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(
            id=recalculation_id,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            query_to__isnull=True,
        )
        .update(status=ExperimentMetricsRecalculation.Status.FAILED)
        == 1
    )


def _recalculation_paused_error(recalculation_id: str) -> NonReportableApplicationError:
    return NonReportableApplicationError(
        f"recalc {recalculation_id} not started: experiment recalculations are paused",
        type=RECALCULATION_PAUSED_ERROR_TYPE,
        non_retryable=True,
    )
