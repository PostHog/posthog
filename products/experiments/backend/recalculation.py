"""Service layer for experiment metrics recalculation.

Module-level free functions (not methods on ExperimentService) so the API view can compose them directly:

- ``request_recalculation`` — idempotent create: returns the active run if one exists, else creates a pending job.
- ``get_latest_recalculation`` — most recent recalc row for an experiment, or ``None``.
- ``get_run_results`` — read-back of per-metric results for a specific run, scoped by recomputing each metric's
  per-run recalc fingerprint (no FK on ExperimentMetricResult; the scoping key lives entirely on the job row +
  the run id).
"""

from uuid import UUID

from rest_framework.exceptions import ValidationError

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models.user import User

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.backend.temporal.recalculation_logic import _find_metric_dict


def _serialize_job(recalc: ExperimentMetricsRecalculation, *, is_existing: bool) -> dict:
    return {
        "id": str(recalc.id),
        "experiment_id": recalc.experiment_id,
        "status": recalc.status,
        "total_metrics": recalc.total_metrics,
        "completed_metrics": recalc.completed_metrics,
        "failed_metrics": recalc.failed_metrics,
        # Output key is metric_errors (serializer field renamed to avoid shadowing Serializer.errors); the model
        # attribute is still recalc.errors.
        "metric_errors": recalc.errors,
        "trigger": recalc.trigger,
        "created_at": recalc.created_at.isoformat(),
        "started_at": recalc.started_at.isoformat() if recalc.started_at else None,
        "completed_at": recalc.completed_at.isoformat() if recalc.completed_at else None,
        "is_existing": is_existing,
    }


def request_recalculation(experiment: Experiment, user: User, trigger: str = "manual") -> dict:
    """Create an idempotent batch recalculation request for all experiment metrics.

    If an active (pending or in_progress) run already exists for this experiment, returns the existing run's
    serialized payload with ``is_existing=True`` — the caller should NOT start a new workflow in that case.
    Otherwise creates a fresh pending row.
    """
    if not experiment.is_launched:
        raise ValidationError("Cannot recalculate metrics for experiment that hasn't started")

    existing = ExperimentMetricsRecalculation.objects.filter(
        experiment=experiment,
        status__in=[
            ExperimentMetricsRecalculation.Status.PENDING,
            ExperimentMetricsRecalculation.Status.IN_PROGRESS,
        ],
    ).first()
    if existing:
        return _serialize_job(existing, is_existing=True)

    recalc = ExperimentMetricsRecalculation.objects.create(
        team=experiment.team,
        experiment=experiment,
        trigger=trigger,
        status=ExperimentMetricsRecalculation.Status.PENDING,
        created_by=user,
    )
    return _serialize_job(recalc, is_existing=False)


def get_latest_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    """Most recent successfully-completed recalculation for an experiment, or None.

    Powers ``GET /metrics_recalculation/latest``: the frontend renders cached results from the last good run.
    Runs that are pending/in_progress/failed are NOT returned — the client tracks those separately by id.
    """
    return (
        ExperimentMetricsRecalculation.objects.filter(
            team=experiment.team,
            experiment=experiment,
            status=ExperimentMetricsRecalculation.Status.COMPLETED,
        )
        .order_by("-created_at")
        .first()
    )


def get_recalculation_by_id(experiment: Experiment, recalculation_id: str) -> ExperimentMetricsRecalculation | None:
    """Return the recalculation row for ``recalculation_id`` if it belongs to ``experiment``, else None.

    Enforces experiment scoping so the id-based GET cannot leak rows from a different experiment in the same team.
    Team scoping is already implicit via the viewset's team filter on ``experiment``. Returns None for a malformed
    UUID rather than raising, so the calling view can answer with a clean 404.
    """
    try:
        uuid_value = UUID(recalculation_id)
    except (ValueError, TypeError):
        return None
    return ExperimentMetricsRecalculation.objects.filter(
        team=experiment.team, experiment=experiment, id=uuid_value
    ).first()


def _recalc_fingerprints_for_run(experiment: Experiment, recalc: ExperimentMetricsRecalculation) -> dict[str, str]:
    """Recompute each metric's per-run recalc fingerprint (strategy 'a': no extra storage).

    Returns ``{metric_uuid: recalc_fp}`` for metrics still resolvable on the experiment. A uuid present on the job
    but no longer on the experiment is skipped (metric removed mid-run).
    """
    stats_method = get_experiment_stats_method(experiment)
    fingerprints: dict[str, str] = {}
    for metric_uuid in recalc.metric_uuids or []:
        metric_dict = _find_metric_dict(experiment, metric_uuid)
        if metric_dict is None:
            continue
        config_fp = compute_metric_fingerprint(
            metric_dict,
            experiment.start_date,
            stats_method,
            experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
        )
        fingerprints[metric_uuid] = compute_recalc_fingerprint(config_fp, str(recalc.id))
    return fingerprints


def get_run_results(recalc: ExperimentMetricsRecalculation) -> list[dict]:
    """Return the ExperimentMetricResult rows that belong to THIS run.

    Scopes by recomputing each metric's recalc fingerprint and filtering ``fingerprint__in`` — never returns
    rows from a previous run or from the timeseries workflow (which uses config fingerprints).
    """
    fingerprints = _recalc_fingerprints_for_run(recalc.experiment, recalc)
    if not fingerprints:
        return []

    rows = ExperimentMetricResult.objects.filter(
        experiment=recalc.experiment, fingerprint__in=list(fingerprints.values())
    )
    return [
        {
            "metric_uuid": row.metric_uuid,
            "status": row.status,
            "result": row.result,
            "error_message": row.error_message,
        }
        for row in rows
    ]
