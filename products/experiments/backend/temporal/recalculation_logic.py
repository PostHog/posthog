"""Synchronous implementation for the metrics recalculation activities.

The thin ``@temporalio.activity.defn`` entrypoints live in ``recalculation_activities`` and delegate here. This
module holds the DB-touching ``_*_sync`` implementations plus the pure helpers they compose from.
"""

from datetime import UTC, datetime
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

import structlog

from posthog.schema import (
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentQuery,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import tag_queries
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.experiments.experiment_metric_fingerprint import compute_metric_fingerprint
from posthog.hogql_queries.experiments.experiment_query_runner import ExperimentQueryRunner
from posthog.hogql_queries.experiments.utils import get_experiment_stats_method
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async

from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.temporal.models import (
    ExperimentMetricToRecalculate,
    MetricRecalculationResult,
    RecalculationProgressUpdate,
)
from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint
from products.experiments.stats.shared.statistics import StatisticError

logger = structlog.get_logger(__name__)

# Cap stored/returned error messages so a pathological traceback can't bloat the Temporal payload (~2 MiB cap).
_MAX_ERROR_MESSAGE_LENGTH = 2000


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _get_recalc_team_id(recalculation_id: str) -> int:
    """Resolve the team_id for a recalc without entering scope yet (chicken-and-egg)."""
    team_id = (
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(id=recalculation_id)
        .values_list("team_id", flat=True)
        .first()
    )
    if team_id is None:
        raise ExperimentMetricsRecalculation.DoesNotExist(
            f"ExperimentMetricsRecalculation {recalculation_id} not found"
        )
    return team_id


@database_sync_to_async
def _discover_experiment_metrics_sync(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    close_old_connections()

    team_id = _get_recalc_team_id(recalculation_id)
    with team_scope(team_id, canonical=True):
        recalculation = ExperimentMetricsRecalculation.objects.select_related("experiment").get(id=recalculation_id)
        experiment = recalculation.experiment

        metrics_to_recalculate: list[ExperimentMetricToRecalculate] = []

        def _add(metric_uuid: str | None, metric_type: str) -> None:
            if metric_uuid:
                metrics_to_recalculate.append(
                    ExperimentMetricToRecalculate(
                        experiment_id=experiment.id, metric_uuid=metric_uuid, metric_type=metric_type
                    )
                )

        # Inline metrics carry their uuid directly on the dict; the metric_type is the source list.
        for source, metric_type in [(experiment.metrics, "primary"), (experiment.metrics_secondary, "secondary")]:
            for metric in source or []:
                _add(metric.get("uuid"), metric_type)

        # Saved (shared) metrics live in the M2M through-model: uuid is on saved_metric.query["uuid"], and
        # primary/secondary is recorded on the link's metadata["type"] (default "primary").
        for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
            saved_query = link.saved_metric.query
            metric_uuid = saved_query.get("uuid") if saved_query else None
            metric_type = link.metadata.get("type", "primary") if link.metadata else "primary"
            _add(metric_uuid, metric_type)

        recalculation.metric_uuids = [m.metric_uuid for m in metrics_to_recalculate]
        recalculation.save(update_fields=["metric_uuids"])

    logger.info(
        "Discovered experiment metrics for recalculation",
        recalculation_id=recalculation_id,
        count=len(metrics_to_recalculate),
    )
    return metrics_to_recalculate


# ---------------------------------------------------------------------------
# Progress (start / finish only — per-metric progress is folded into the calc step)
# ---------------------------------------------------------------------------


@database_sync_to_async
def _update_recalculation_progress_sync(update: RecalculationProgressUpdate) -> str | None:
    close_old_connections()

    team_id = _get_recalc_team_id(update.recalculation_id)
    with team_scope(team_id, canonical=True):
        # Start: write the data-window end + started_at + initial state under a first-write-wins guard so a
        # Temporal retry of this activity can't move query_to forward (which would orphan any rows persisted by
        # calc activities still in flight from the prior attempt).
        if update.mark_started:
            proposed_query_to = datetime.now(UTC)
            won = (
                ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id, query_to__isnull=True).update(
                    query_to=proposed_query_to,
                    started_at=timezone.now(),
                    status=update.status or ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                    total_metrics=update.total_metrics if update.total_metrics is not None else 0,
                    metric_uuids=update.metric_uuids if update.metric_uuids is not None else [],
                )
                == 1
            )
            if won:
                return proposed_query_to.isoformat()
            existing_query_to = (
                ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id)
                .values_list("query_to", flat=True)
                .first()
            )
            return existing_query_to.isoformat() if existing_query_to is not None else None

        # Finish: same first-write-wins guard so a retried mark_completed activity doesn't re-stamp the
        # completion timestamp (and, by symmetry with mark_started, doesn't reopen a closed run).
        if update.mark_completed:
            ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id, completed_at__isnull=True).update(
                completed_at=timezone.now(),
                status=update.status or ExperimentMetricsRecalculation.Status.COMPLETED,
            )
            return None

        # Plain status or counter updates (no lifecycle transition) — idempotent on the value level.
        updates: dict[str, Any] = {}
        if update.status:
            updates["status"] = update.status
        if update.total_metrics is not None:
            updates["total_metrics"] = update.total_metrics
        if update.metric_uuids is not None:
            updates["metric_uuids"] = update.metric_uuids
        if updates:
            ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id).update(**updates)
        return None


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


def _find_metric_dict(experiment: Experiment, metric_uuid: str) -> dict | None:
    """Resolve a metric_uuid to its definition dict, across inline AND saved/shared metrics.

    Inline metrics are dicts in experiment.metrics / metrics_secondary. Saved metrics live on the M2M
    through-model and carry their definition (with uuid) in saved_metric.query.
    """
    for metric in (experiment.metrics or []) + (experiment.metrics_secondary or []):
        if metric.get("uuid") == metric_uuid:
            return metric

    for link in experiment.experimenttosavedmetric_set.select_related("saved_metric").all():
        saved_query = link.saved_metric.query
        if saved_query and saved_query.get("uuid") == metric_uuid:
            return saved_query

    return None


# Modern ExperimentMetric types (kind="ExperimentMetric"). Legacy Trends/Funnels metrics never enter this
# workflow, so there is no fallback — an unexpected metric_type surfaces as a calculation-step error.
_METRIC_BUILDERS = {
    "mean": ExperimentMeanMetric,
    "funnel": ExperimentFunnelMetric,
    "ratio": ExperimentRatioMetric,
    "retention": ExperimentRetentionMetric,
}


def _build_metric(
    metric_dict: dict,
) -> ExperimentMeanMetric | ExperimentFunnelMetric | ExperimentRatioMetric | ExperimentRetentionMetric:
    return _METRIC_BUILDERS[metric_dict["metric_type"]](**metric_dict)


def _record_failure(recalculation_id: str, metric_uuid: str, step: str, message: str) -> None:
    """Merge the error entry into metric_errors under a row lock (no lost updates between concurrent failures).

    Idempotent on Temporal retries: the dict is keyed by metric_uuid, so re-running this for the same metric
    just overwrites the existing entry with a fresh timestamp.
    """
    capped = message[:_MAX_ERROR_MESSAGE_LENGTH]
    with transaction.atomic():
        recalc = ExperimentMetricsRecalculation.objects.select_for_update().get(id=recalculation_id)
        metric_errors = recalc.metric_errors or {}
        metric_errors[metric_uuid] = {"step": step, "message": capped, "timestamp": timezone.now().isoformat()}
        recalc.metric_errors = metric_errors
        recalc.save(update_fields=["metric_errors"])


def _store_result(
    *,
    experiment_id: int,
    metric_uuid: str,
    recalc_fp: str,
    query_from: datetime,
    query_to: datetime,
    status: str,
    result: dict | None,
    error_message: str | None,
) -> None:
    ExperimentMetricResult.objects.update_or_create(
        experiment_id=experiment_id,
        metric_uuid=metric_uuid,
        fingerprint=recalc_fp,
        query_to=query_to,
        defaults={
            "query_from": query_from,
            "status": status,
            "result": result,
            "query_id": None,
            "completed_at": timezone.now() if status == ExperimentMetricResult.Status.COMPLETED else None,
            "error_message": error_message,
        },
    )


def _fail(recalculation_id: str, metric_uuid: str, step: str, message: str) -> MetricRecalculationResult:
    """Record a failure on the job (lookup step: job-only; calculation step: also persists a result row upstream)."""
    _record_failure(recalculation_id, metric_uuid, step, message)
    return MetricRecalculationResult(
        metric_uuid=metric_uuid, success=False, error_step=step, error_message=message[:_MAX_ERROR_MESSAGE_LENGTH]
    )


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


@database_sync_to_async
def _calculate_experiment_metric_for_recalculation_sync(
    experiment_id: int, metric_uuid: str, recalculation_id: str, query_to: str
) -> MetricRecalculationResult:
    close_old_connections()

    query_to_dt = datetime.fromisoformat(query_to)
    team_id = _get_recalc_team_id(recalculation_id)

    with team_scope(team_id, canonical=True):
        try:
            experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        except Experiment.DoesNotExist:
            return _fail(recalculation_id, metric_uuid, "discovery", f"Experiment {experiment_id} not found or deleted")

        metric_dict = _find_metric_dict(experiment, metric_uuid)
        if metric_dict is None:
            return _fail(
                recalculation_id,
                metric_uuid,
                "discovery",
                f"Metric {metric_uuid} not found in experiment {experiment_id}",
            )

        if not experiment.start_date:
            return _fail(recalculation_id, metric_uuid, "discovery", f"Experiment {experiment_id} has no start_date")

        config_fp = compute_metric_fingerprint(
            metric_dict,
            experiment.start_date,
            get_experiment_stats_method(experiment),
            experiment.exposure_criteria,
            only_count_matured_users=experiment.only_count_matured_users,
        )
        recalc_fp = compute_recalc_fingerprint(config_fp, recalculation_id)

        try:
            # Metric build + query live inside the try so unexpected shapes surface as a calculation-step failure.
            runner = ExperimentQueryRunner(
                query=ExperimentQuery(experiment_id=experiment_id, metric=_build_metric(metric_dict)),
                team=experiment.team,
                workload=Workload.OFFLINE,
            )
            tag_queries(trigger="warming/experiment_metrics_recalculation")
            result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            result_dict = result.model_dump(mode="json")

            _store_result(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                recalc_fp=recalc_fp,
                query_from=experiment.start_date,
                query_to=query_to_dt,
                status=ExperimentMetricResult.Status.COMPLETED,
                result=result_dict,
                error_message=None,
            )
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        except (StatisticError, ZeroDivisionError) as e:
            # Expected "not enough data" style failures — warn, no exception capture.
            message = str(e)[:_MAX_ERROR_MESSAGE_LENGTH]
            _store_result(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                recalc_fp=recalc_fp,
                query_from=experiment.start_date,
                query_to=query_to_dt,
                status=ExperimentMetricResult.Status.FAILED,
                result=None,
                error_message=message,
            )
            logger.warning(
                "Experiment metric recalculation failed due to insufficient data",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                error=message,
            )
            return _fail(recalculation_id, metric_uuid, "calculation", message)

        except Exception as e:
            message = str(e)[:_MAX_ERROR_MESSAGE_LENGTH]
            capture_exception(
                e,
                additional_properties={
                    "experiment_id": experiment_id,
                    "metric_uuid": metric_uuid,
                    "recalculation_id": recalculation_id,
                },
            )
            _store_result(
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                recalc_fp=recalc_fp,
                query_from=experiment.start_date,
                query_to=query_to_dt,
                status=ExperimentMetricResult.Status.FAILED,
                result=None,
                error_message=message,
            )
            logger.exception(
                "Experiment metric recalculation failed",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
            )
            return _fail(recalculation_id, metric_uuid, "calculation", message)
