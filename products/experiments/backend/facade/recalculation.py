"""Metrics recalculation runs of an experiment, and the start of its timeseries recalculation workflow."""

from typing import Any

from posthog.models.user import User

from products.experiments.backend import recalculation
from products.experiments.backend.facade.contracts import (
    ActiveMetricsRecalculation,
    LatestMetricsRecalculation,
    MetricRecalculationResult,
    MetricsRecalculationRun,
    RequestedMetricsRecalculation,
)
from products.experiments.backend.facade.enums import ExperimentResultConfigurationStatus
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.recalculation import start_timeseries_recalculation_workflow

__all__ = [
    "AGENT_MCP_RECALCULATION_TRIGGER",
    "METRICS_RECALCULATION_REQUEST_TRIGGER_CHOICES",
    "METRICS_RECALCULATION_STATUS_CHOICES",
    "get_latest_metrics_recalculation",
    "get_metrics_recalculation",
    "request_metrics_recalculation",
    "start_timeseries_recalculation_workflow",
]

# The model's choices, as (value, label) pairs. A serializer field with exactly these pairs keeps the OpenAPI enum name
# that the model's choices class gives them.
METRICS_RECALCULATION_STATUS_CHOICES: list[tuple[str, str]] = [
    (value, str(label)) for value, label in ExperimentMetricsRecalculation.Status.choices
]
METRICS_RECALCULATION_REQUEST_TRIGGER_CHOICES: list[tuple[str, str]] = [
    (value, str(label)) for value, label in ExperimentMetricsRecalculation.RequestTrigger.choices
]
AGENT_MCP_RECALCULATION_TRIGGER: str = ExperimentMetricsRecalculation.Trigger.AGENT_MCP


def _get_experiment(team_id: int, experiment_id: int) -> Experiment:
    # The recalculation paths read the team and the flag of the experiment.
    return Experiment.objects.select_related("team", "feature_flag").get(team_id=team_id, id=experiment_id)


def _job_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(payload["id"]),
        "experiment_id": payload["experiment_id"],
        "status": payload["status"],
        "total_metrics": payload["total_metrics"],
        "completed_metrics": payload["completed_metrics"],
        "failed_metrics": payload["failed_metrics"],
        "metric_errors": payload["metric_errors"],
        "created_at": payload["created_at"],
        "started_at": payload["started_at"],
        "completed_at": payload["completed_at"],
        "query_to": payload["query_to"],
    }


def _run_fields(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        **_job_fields(payload),
        "metric_retries": payload["metric_retries"],
        "results": tuple(
            MetricRecalculationResult(
                metric_uuid=row["metric_uuid"],
                status=row["status"],
                result=row["result"],
                error_message=row["error_message"],
                configuration_status=ExperimentResultConfigurationStatus(row["configuration_status"]),
            )
            for row in payload["results"]
        ),
        "rows_read": payload.get("rows_read"),
        "estimated_rows_total": payload.get("estimated_rows_total"),
    }


def request_metrics_recalculation(
    *, team_id: int, experiment_id: int, user: User, trigger: str
) -> RequestedMetricsRecalculation:
    """Request a recalculation of all the experiment's metrics, and start the workflow of a new run.

    An active run is reused, and so is a fresh enough run for a `stale_refresh` trigger. An experiment that started too
    long ago gets a run that is already failed, and no workflow. Raises `RecalculationRateLimited` (a DRF throttle) for
    a user trigger soon after the latest run, and a DRF `ValidationError` for an experiment that has not started.
    """
    payload = recalculation.request_and_start_recalculation(_get_experiment(team_id, experiment_id), user, trigger)
    return RequestedMetricsRecalculation(**_job_fields(payload), is_existing=payload["is_existing"])


def get_latest_metrics_recalculation(*, team_id: int, experiment_id: int) -> LatestMetricsRecalculation | None:
    """The newest terminal run, else a placeholder from fresh timeseries data, else the active run. None when the
    experiment has none of them."""
    payload = recalculation.build_latest_payload(_get_experiment(team_id, experiment_id))
    if payload is None:
        return None
    active_run = payload.get("active_run")
    return LatestMetricsRecalculation(
        **_run_fields(payload),
        active_run=ActiveMetricsRecalculation(id=active_run["id"], status=active_run["status"]) if active_run else None,
        result_source=payload.get("result_source", "recalculation"),
        exceeds_recalculation_age_limit=payload["exceeds_recalculation_age_limit"],
    )


def get_metrics_recalculation(
    *, team_id: int, experiment_id: int, recalculation_id: str
) -> MetricsRecalculationRun | None:
    """The run with this id, when it belongs to the experiment. None for another experiment's run and a malformed id."""
    recalc = recalculation.get_recalculation_by_id(_get_experiment(team_id, experiment_id), recalculation_id)
    if recalc is None:
        return None
    return MetricsRecalculationRun(**_run_fields(recalculation.build_run_payload(recalc)))
