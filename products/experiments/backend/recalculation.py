"""Service layer for experiment metrics recalculation.

Module-level free functions (not methods on ExperimentService) so the API view can compose them directly:

- ``request_recalculation`` — idempotent create: returns the active run if one exists, else creates a pending job.
- ``get_latest_recalculation`` — most recent recalc row for an experiment, or ``None``.
- ``get_run_results`` — read-back of per-metric results for a specific run, scoped by recomputing each metric's
  per-run recalc fingerprint (no FK on ExperimentMetricResult; the scoping key lives entirely on the job row +
  the run id).
"""

from datetime import timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.models.scoping import team_scope
from posthog.models.user import User

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.backend.temporal.recalculation_logic import _find_metric_dict

# How long an active (PENDING/IN_PROGRESS) row blocks new recalculations. Beyond this, the row is treated as
# stale and a fresh recalc is allowed. Sized to be safely above the workflow's worst-case end-to-end runtime
# (discovery retries + per-metric calc retries + progress activities) so a legitimately-slow run can finish
# without being clobbered, but tight enough that an operator can recover within an hour if the workflow
# never started (Temporal connect failure, transient infra issue, etc.). See the rollback in views.py for the
# happy-path failure handling; this TTL is the defense-in-depth backstop if that rollback itself fails.
_STALE_RECALC_THRESHOLD = timedelta(minutes=30)


def _derive_counters(recalc: ExperimentMetricsRecalculation, results: list[dict] | None = None) -> tuple[int, int]:
    """Counters are not stored on the row (PR1 contract): they're derived on read from result rows + errors.

    `completed_metrics` = ExperimentMetricResult rows with status=COMPLETED for this run's fingerprints.
    `failed_metrics`    = ExperimentMetricResult rows with status=FAILED + metric_errors keys that never made
                          it to a result row (discovery-step failures).

    Accepts an optional pre-computed `results` list to avoid recomputing fingerprints on the GET path where
    the same list is also surfaced to the client.
    """
    rows = results if results is not None else get_run_results(recalc)
    completed = sum(1 for r in rows if r["status"] == ExperimentMetricResult.Status.COMPLETED)
    failed_in_rows = sum(1 for r in rows if r["status"] == ExperimentMetricResult.Status.FAILED)
    uuids_with_row = {r["metric_uuid"] for r in rows}
    discovery_only_failures = sum(1 for uuid in (recalc.metric_errors or {}) if uuid not in uuids_with_row)
    return completed, failed_in_rows + discovery_only_failures


def build_job_payload(
    recalc: ExperimentMetricsRecalculation,
    *,
    is_existing: bool | None = None,
    results: list[dict] | None = None,
) -> dict:
    """Shape a recalc row + derived counters as a dict the serializer can re-serialize.

    Returns model-native values (datetimes, ints, dicts) — DRF handles the wire format. The POST path passes
    `is_existing` to signal whether the workflow needs starting; the GET paths pass `results` so the same row
    list backs both the derived counters and the response's `results` field (no duplicate fingerprint work).
    """
    completed_metrics, failed_metrics = _derive_counters(recalc, results=results)
    payload: dict = {
        "id": str(recalc.id),
        "experiment_id": recalc.experiment_id,
        "status": recalc.status,
        "total_metrics": recalc.total_metrics,
        "completed_metrics": completed_metrics,
        "failed_metrics": failed_metrics,
        "metric_errors": recalc.metric_errors,
        "trigger": recalc.trigger,
        "created_at": recalc.created_at,
        "started_at": recalc.started_at,
        "completed_at": recalc.completed_at,
    }
    if is_existing is not None:
        payload["is_existing"] = is_existing
    return payload


def request_recalculation(experiment: Experiment, user: User, trigger: str = "manual") -> dict:
    """Create an idempotent batch recalculation request for all experiment metrics.

    If an active (pending or in_progress) run already exists for this experiment, returns the existing run's
    serialized payload with ``is_existing=True`` — the caller should NOT start a new workflow in that case.
    Otherwise creates a fresh pending row.
    """
    if not experiment.is_launched:
        raise ValidationError("Cannot recalculate metrics for experiment that hasn't started")

    with team_scope(experiment.team_id, canonical=True):
        # Activity-aware staleness: PENDING rows anchor on created_at (workflow never reached its start
        # activity); IN_PROGRESS rows anchor on started_at (workflow began executing then stalled). A row past
        # the threshold is treated as dead and skipped, so a fresh recalc can start. Without this, a PENDING
        # row left orphaned by a Temporal-connect failure that also lost its rollback UPDATE would permanently
        # lock the experiment out of recalculations.
        threshold = timezone.now() - _STALE_RECALC_THRESHOLD
        existing = (
            ExperimentMetricsRecalculation.objects.filter(experiment=experiment)
            .filter(
                Q(status=ExperimentMetricsRecalculation.Status.PENDING, created_at__gte=threshold)
                | Q(status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at__gte=threshold)
            )
            .first()
        )
        if existing:
            return build_job_payload(existing, is_existing=True)

        # No fresh active row, but stale tombstones might still hold the per-experiment uniqueness constraint
        # (unique_active_metrics_recalculation_per_experiment). Mark them FAILED so the constraint releases
        # and the new row can land. Status reflects reality — these workflows are not coming back.
        ExperimentMetricsRecalculation.objects.filter(
            experiment=experiment,
            status__in=[
                ExperimentMetricsRecalculation.Status.PENDING,
                ExperimentMetricsRecalculation.Status.IN_PROGRESS,
            ],
        ).update(status=ExperimentMetricsRecalculation.Status.FAILED, completed_at=timezone.now())

        recalc = ExperimentMetricsRecalculation.objects.create(
            team=experiment.team,
            experiment=experiment,
            trigger=trigger,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            created_by=user,
        )
        return build_job_payload(recalc, is_existing=False)


def get_latest_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    """Most recent successfully-completed recalculation for an experiment, or None.

    Powers ``GET /metrics_recalculation/latest``: the frontend renders cached results from the last good run.
    Runs that are pending/in_progress/failed are NOT returned — the client tracks those separately by id.
    """
    with team_scope(experiment.team_id, canonical=True):
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
    Returns None for a malformed UUID rather than raising, so the calling view can answer with a clean 404.
    """
    try:
        uuid_value = UUID(recalculation_id)
    except (ValueError, TypeError):
        return None
    with team_scope(experiment.team_id, canonical=True):
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
