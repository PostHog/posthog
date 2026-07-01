"""Synchronous implementation for the metrics recalculation activities.

The thin ``@temporalio.activity.defn`` entrypoints live in ``recalculation_activities`` and delegate here. This
module holds the DB-touching ``_*_sync`` implementations plus the pure helpers they compose from.
"""

import time
import dataclasses
from datetime import datetime
from typing import Any

from django.db import close_old_connections, transaction
from django.utils import timezone

import structlog
from clickhouse_driver.errors import ServerException
from temporalio.exceptions import ApplicationError

from posthog.schema import ExperimentQuery

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.errors import look_up_clickhouse_error_code_meta
from posthog.event_usage import groups
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.scoping import team_scope
from posthog.ph_client import ph_scoped_capture
from posthog.sync import database_sync_to_async

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window_end
from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.temporal.metric_resolution import build_metric, find_metric_dict
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


def _get_recalc_state(recalculation_id: str) -> _RecalcState:
    """Resolve the recalc row's identifying fields without entering scope yet (chicken-and-egg)."""
    row = (
        ExperimentMetricsRecalculation.objects.unscoped()
        .filter(id=recalculation_id)
        .values("team_id", "experiment_id", "metric_uuids", "query_to")
        .first()
    )
    if row is None:
        # Deterministic: the row's not coming back (bogus id, manual delete, cascade from team/experiment).
        # Non-retryable so Temporal terminates promptly instead of burning retries on each activity.
        raise ApplicationError(
            f"ExperimentMetricsRecalculation {recalculation_id} not found",
            non_retryable=True,
        )
    return _RecalcState(
        team_id=row["team_id"],
        experiment_id=row["experiment_id"],
        metric_uuids=row["metric_uuids"] or [],
        query_to=row["query_to"],
    )


def discover_experiment_metrics(experiment: Experiment) -> list[ExperimentMetricToRecalculate]:
    """All metrics to recalculate for an experiment, in (primary, secondary, saved) order.

    Single source of truth for "which metrics does this experiment have" — used both to set
    ``total_metrics`` at recalculation-create time and by the discovery activity. Touches the DB
    (saved-metric links), so call inside a team scope / sync context.

    Note: this sync helper takes an ``Experiment``. The async Temporal activity in
    ``recalculation_activities.py`` shares the name but takes a ``recalculation_id`` — disambiguate by
    import path and argument type at the call site.
    """
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

    return metrics_to_recalculate


@database_sync_to_async
def _discover_experiment_metrics_sync(recalculation_id: str) -> list[ExperimentMetricToRecalculate]:
    close_old_connections()

    state = _get_recalc_state(recalculation_id)
    with team_scope(state.team_id, canonical=True):
        recalculation = ExperimentMetricsRecalculation.objects.select_related("experiment").get(id=recalculation_id)
        experiment = recalculation.experiment

        metrics_to_recalculate = discover_experiment_metrics(experiment)

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

    if update.mark_started == update.mark_completed:
        # Contract: exactly one of mark_started / mark_completed per call. Both-true or neither-true is a
        # workflow bug — fail non-retryable so Temporal terminates promptly.
        raise ApplicationError(
            "RecalculationProgressUpdate must set exactly one of mark_started or mark_completed",
            non_retryable=True,
        )

    state = _get_recalc_state(update.recalculation_id)
    with team_scope(state.team_id, canonical=True):
        # Start: write the data-window end + started_at + initial state under a first-write-wins guard so a
        # Temporal retry of this activity can't move query_to forward (which would orphan any rows persisted by
        # calc activities still in flight from the prior attempt).
        if update.mark_started:
            # query_to is the run's data-window end, not bare "now": for a stopped experiment
            # experiment_window_end resolves it to end_date (a fixed value), so repeated recalcs reuse the
            # same (fingerprint, query_to)-keyed result row instead of appending a redundant post-end
            # timeseries point on every run. A running experiment still advances with now.
            experiment = Experiment.objects.get(id=state.experiment_id)
            proposed_query_to = experiment_window_end(experiment, timezone.now())
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
        won = (
            ExperimentMetricsRecalculation.objects.filter(id=update.recalculation_id, completed_at__isnull=True).update(
                completed_at=timezone.now(),
                status=update.status or ExperimentMetricsRecalculation.Status.COMPLETED,
            )
            == 1
        )
        # Emit the run-level analytics event only on the winning (first) completion, so a retried
        # mark_completed doesn't double-count.
        if won:
            _capture_results_refresh_completed(update)
        return None


def _capture_results_refresh_completed(update: RecalculationProgressUpdate) -> None:
    """Run-level analytics: 'experiment results refresh completed' with the final counts. Mirrors the
    legacy client-side event. Telemetry must never fail the activity, so swallow any error."""
    try:
        recalc = (
            ExperimentMetricsRecalculation.objects.select_related("experiment", "experiment__team")
            .filter(id=update.recalculation_id)
            .first()
        )
        if recalc is None:
            return
        experiment = recalc.experiment
        team = experiment.team
        distinct_id = (
            experiment.created_by.distinct_id
            if experiment.created_by and experiment.created_by.distinct_id
            else f"team_{team.id}"
        )
        total_duration_ms = (
            round((recalc.completed_at - recalc.created_at).total_seconds() * 1000)
            if recalc.completed_at and recalc.created_at
            else None
        )
        # Split the full duration into the time the workflow actually executed (start activity to finish)
        # and the time it waited in the queue before the start activity ran (request to start). Their sum
        # is total_duration_ms. started_at is set by the start activity, so it is present on any completed run.
        execution_duration_ms = (
            round((recalc.completed_at - recalc.started_at).total_seconds() * 1000)
            if recalc.completed_at and recalc.started_at
            else None
        )
        queue_duration_ms = (
            round((recalc.started_at - recalc.created_at).total_seconds() * 1000)
            if recalc.started_at and recalc.created_at
            else None
        )
        # Hours since the experiment launched, matching the legacy frontend definition exactly
        # (now - start_date, ignoring end_date) so dashboards can share the >12h filter across paths.
        experiment_duration_hours = (
            round((timezone.now() - experiment.start_date).total_seconds() / 3600) if experiment.start_date else None
        )
        primary_metrics_count = len(experiment.metrics or [])
        secondary_metrics_count = len(experiment.metrics_secondary or [])
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event="experiment results refresh completed",
                properties={
                    "experiment_id": experiment.id,
                    "team_id": team.id,
                    "recalculation_id": str(recalc.id),
                    "status": recalc.status,
                    "total_metrics": recalc.total_metrics,
                    "succeeded_metrics": update.succeeded_metrics,
                    "failed_metrics": update.failed_metrics,
                    "total_duration_ms": total_duration_ms,
                    "execution_duration_ms": execution_duration_ms,
                    "queue_duration_ms": queue_duration_ms,
                    "trigger": recalc.trigger,
                    "execution_mode": "recalculation",
                    # Legacy-named aliases + missing properties for parity with the frontend
                    # 'experiment results refresh completed' event, so the original experiments
                    # dashboards work against workflow runs with the same property names.
                    "triggered_by": recalc.trigger,
                    "successful_count": update.succeeded_metrics,
                    "errored_count": update.failed_metrics,
                    "cached_count": 0,
                    "total_metrics_count": recalc.total_metrics,
                    "primary_metrics_count": primary_metrics_count,
                    "secondary_metrics_count": secondary_metrics_count,
                    "experiment_status": experiment.status or experiment.computed_status,
                    "experiment_duration_hours": experiment_duration_hours,
                },
                groups=groups(organization=team.organization, team=team),
            )
    except Exception:
        logger.warning(
            "experiment_results_refresh_completed_capture_failed",
            recalculation_id=update.recalculation_id,
            exc_info=True,
        )


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------


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
    query_id: str | None = None,
) -> None:
    # Upsert on the true unique key (experiment, metric_uuid, query_to); fingerprint goes in defaults so a row
    # already occupying that key under a different fingerprint is updated in place, not inserted as a colliding
    # duplicate. This heals rows written under the old per-run fingerprint scheme.
    ExperimentMetricResult.objects.update_or_create(
        experiment_id=experiment_id,
        metric_uuid=metric_uuid,
        query_to=query_to,
        defaults={
            "fingerprint": recalc_fp,
            "query_from": query_from,
            "status": status,
            "result": result,
            "query_id": query_id,
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
# Product analytics (recalculation flow)
#
# These mirror the legacy client-side events ('experiment metric finished' / 'experiment metric error'),
# now that metrics are computed on the backend instead of in the browser. execution_mode='recalculation'
# distinguishes them from legacy events on the same dashboards.
# ---------------------------------------------------------------------------


def _capture_experiment_metric_event(
    experiment: Experiment,
    metric_uuid: str,
    metric_type: str,
    metric_dict: dict | None,
    event: str,
    extra_properties: dict[str, Any],
) -> None:
    """Emit a per-metric product analytics event. Telemetry must never fail the activity, so any error
    is swallowed. Attributed to the experiment creator, falling back to a team-scoped distinct_id.

    `metric_type` is the primary/secondary classification carried from discovery
    (`ExperimentMetricToRecalculate.metric_type`), threaded through the workflow + activity args so the
    capture path doesn't have to re-query the M2M to resolve it.
    """
    try:
        team = experiment.team
        distinct_id = (
            experiment.created_by.distinct_id
            if experiment.created_by and experiment.created_by.distinct_id
            else f"team_{team.id}"
        )
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event=event,
                properties={
                    "experiment_id": experiment.id,
                    "team_id": team.id,
                    "metric_uuid": metric_uuid,
                    "metric_kind": (metric_dict or {}).get("metric_type"),
                    "is_primary": metric_type == "primary",
                    "execution_mode": "recalculation",
                    **extra_properties,
                },
                groups=groups(organization=team.organization, team=team),
            )
    except Exception:
        logger.warning(
            "experiment_metric_event_capture_failed",
            event=event,
            experiment_id=experiment.id,
            metric_uuid=metric_uuid,
            exc_info=True,
        )


# error_type values mirror the client-side `classifyError` taxonomy (experimentLogic.tsx) so
# recalculation failures land on the same dashboards as the legacy client events.
def _classify_query_error_type(e: Exception) -> str:
    if isinstance(e, (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong)):
        return "timeout"
    if isinstance(e, ClickHouseQueryMemoryLimitExceeded):
        return "out_of_memory"
    if isinstance(e, ServerException):
        name = look_up_clickhouse_error_code_meta(e).name
        if name in ("TIMEOUT_EXCEEDED", "SOCKET_TIMEOUT"):
            return "timeout"
        if name == "MEMORY_LIMIT_EXCEEDED":
            return "out_of_memory"
    return "server_error"


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


@database_sync_to_async
def _calculate_experiment_metric_for_recalculation_sync(
    experiment_id: int,
    metric_uuid: str,
    recalculation_id: str,
    query_to: str,
    metric_type: str = "primary",
    is_final_attempt: bool = True,
) -> MetricRecalculationResult:
    close_old_connections()

    try:
        query_to_dt = datetime.fromisoformat(query_to)
    except ValueError as e:
        raise ApplicationError(
            f"query_to {query_to!r} is not a valid ISO datetime string: {e}",
            non_retryable=True,
        )
    state = _get_recalc_state(recalculation_id)

    # Defense-in-depth at the activity boundary: the workflow constructs all four args from its own state,
    # so a mismatch here means a workflow bug, not a data issue. Fail non-retryable so Temporal terminates
    # the run promptly rather than burning retries on a deterministic failure.
    if experiment_id != state.experiment_id:
        raise ApplicationError(
            f"experiment_id {experiment_id} does not match recalc.experiment_id {state.experiment_id}",
            non_retryable=True,
        )
    if metric_uuid not in state.metric_uuids:
        raise ApplicationError(
            f"metric_uuid {metric_uuid} is not in recalc {recalculation_id}'s metric set",
            non_retryable=True,
        )
    if state.query_to is None:
        raise ApplicationError(
            f"recalc {recalculation_id} has no query_to set — calculate activity ran before start activity",
            non_retryable=True,
        )
    if query_to_dt != state.query_to:
        raise ApplicationError(
            f"query_to {query_to_dt.isoformat()} does not match recalc.query_to {state.query_to.isoformat()}",
            non_retryable=True,
        )

    with team_scope(state.team_id, canonical=True):
        try:
            experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        except Experiment.DoesNotExist:
            return _fail(recalculation_id, metric_uuid, "discovery", f"Experiment {experiment_id} not found or deleted")

        metric_dict = find_metric_dict(experiment, metric_uuid)
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
        recalc_fp = compute_recalc_fingerprint(config_fp)

        # Skip the query if this metric is already computed for this exact config and window; a config change
        # changes the fingerprint, so a stale result won't match and recomputes.
        already_computed = ExperimentMetricResult.objects.filter(
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            query_to=query_to_dt,
            fingerprint=recalc_fp,
            status=ExperimentMetricResult.Status.COMPLETED,
        ).exists()
        if already_computed:
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        # Deterministic per-metric-per-run id. ClickHouse stamps it into the query_id as
        # `{team_id}_{client_query_id}_{random}`, so the stored value is a greppable prefix for
        # `system.query_log` (covers every attempt, including Temporal retries). Bound before the try so the
        # failure paths can always persist it.
        client_query_id = f"experiment_metric_recalc_{recalculation_id}_{metric_uuid}"

        calc_started_at = time.perf_counter()
        try:
            # Metric build + query live inside the try so unexpected shapes surface as a calculation-step failure.
            # as_of pins the run's shared query_to as the window's evaluation instant (the runner caps it at
            # end_date). Without it each metric defaults to its own now(), giving slightly different windows —
            # defeating the "one query_to for the whole run" guarantee.
            runner = ExperimentQueryRunner(
                query=ExperimentQuery(experiment_id=experiment_id, metric=build_metric(metric_dict)),
                team=experiment.team,
                as_of=query_to_dt,
                workload=Workload.OFFLINE,
                # Userless background recompute. Warehouse access is enforced when the metric is authored,
                # so resolve warehouse tables here instead of failing closed.
                bypass_warehouse_access_control=True,
            )

            # Attribute CH load back to this team + product so query_log analysis can tell whose recalc is
            # expensive without reverse-engineering the trigger string.
            tag_queries(
                trigger="warming/experiment_metrics_recalculation",
                team_id=state.team_id,
                product=Product.EXPERIMENTS,
                feature=Feature.CACHE_WARMUP,
                client_query_id=client_query_id,
            )
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
                query_id=client_query_id,
            )
            _capture_experiment_metric_event(
                experiment,
                metric_uuid,
                metric_type,
                metric_dict,
                "experiment metric finished",
                {"duration_ms": round((time.perf_counter() - calc_started_at) * 1000)},
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
                query_id=client_query_id,
            )
            logger.warning(
                "Experiment metric recalculation failed due to insufficient data",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                error=message,
            )
            _capture_experiment_metric_event(
                experiment,
                metric_uuid,
                metric_type,
                metric_dict,
                "experiment metric error",
                {
                    "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                    "error_type": "insufficient_data",
                    "error_message": message,
                },
            )
            return _fail(recalculation_id, metric_uuid, "calculation", message)

        except Exception as e:
            # Could be transient (ClickHouse connection blip, network glitch, or other infrastructure issue).
            # Persist the failure ONLY on the final attempt, then re-raise; on earlier attempts we re-raise
            # without persisting so Temporal retries while the metric stays in its loading/dim state on the
            # frontend, rather than flashing an error for a failure that may yet succeed on the next attempt.
            # StatisticError and ZeroDivisionError are handled above as permanent and return success=False.
            message = str(e)[:_MAX_ERROR_MESSAGE_LENGTH]
            capture_exception(
                e,
                additional_properties={
                    "experiment_id": experiment_id,
                    "metric_uuid": metric_uuid,
                    "recalculation_id": recalculation_id,
                },
            )
            if is_final_attempt:
                _store_result(
                    experiment_id=experiment_id,
                    metric_uuid=metric_uuid,
                    recalc_fp=recalc_fp,
                    query_from=experiment.start_date,
                    query_to=query_to_dt,
                    status=ExperimentMetricResult.Status.FAILED,
                    result=None,
                    error_message=message,
                    query_id=client_query_id,
                )
                _record_failure(recalculation_id, metric_uuid, "calculation", message)
                # Emit only on the terminal failure (retries exhausted) — the error the user actually
                # sees. error_type mirrors the client taxonomy so it lands on the same dashboards.
                # Earlier attempts re-raise silently to avoid double-counting a failure that may still succeed.
                _capture_experiment_metric_event(
                    experiment,
                    metric_uuid,
                    metric_type,
                    metric_dict,
                    "experiment metric error",
                    {
                        "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                        "error_type": _classify_query_error_type(e),
                        "error_message": message,
                    },
                )
            logger.exception(
                "Experiment metric recalculation failed",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                is_final_attempt=is_final_attempt,
            )
            raise
