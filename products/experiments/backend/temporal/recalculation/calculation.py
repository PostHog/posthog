"""Calculation of one metric for a recalculation run, with its query cancel and its out-of-time failure."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from django.db import close_old_connections, transaction

import structlog
from temporalio.exceptions import ApplicationError

from posthog.schema import ExperimentQuery, PrecomputationMode

from posthog.clickhouse.cancel import cancel_query_on_cluster
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions import ClickHouseAtCapacity
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models.scoping import team_scope
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.errors import NonReportableApplicationError

from products.experiments.backend.hogql_queries.error_handling import classify_experiment_query_error
from products.experiments.backend.hogql_queries.experiment_query_runner import ExperimentQueryRunner
from products.experiments.backend.hogql_queries.utils import sanitize_non_finite
from products.experiments.backend.metric_calculation.config import (
    get_metric_calculation_config,
    team_experiments_configs,
)
from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_resolution import build_metric
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricsRecalculation
from products.experiments.backend.temporal.models import (
    CAPACITY_MAX_METRIC_ATTEMPTS,
    MAX_METRIC_ATTEMPTS,
    METRIC_CALC_MAX_EXECUTION_TIME_SECONDS,
    NON_RETRYABLE_ERROR_TYPES,
    TIMEOUT_MAX_METRIC_ATTEMPTS,
    MetricOutOfTimeFailure,
    MetricRecalculationResult,
)
from products.experiments.backend.temporal.recalculation.routing import recalculation_clickhouse_user
from products.experiments.stats.shared.statistics import StatisticError

from . import analytics, attempt_records, run_state

logger = structlog.get_logger(__name__)


_OUT_OF_TIME_MESSAGE = "The calculation ran out of time."

# A query kill on the pool that runs the calculations would wait behind the query it kills.
_CANCELLATION_EXECUTOR = ThreadPoolExecutor(max_workers=10, thread_name_prefix="experiment-recalc-cancel")


def _client_query_id(recalculation_id: str, metric_uuid: str, attempt: int) -> str:
    """The ClickHouse client_query_id this metric's recalc query runs under.

    The calculation path tags its query with this, and the cancellation path kills the query by it, so both
    sides must derive it the same way.

    The attempt keeps one attempt's cancellation off another attempt's query, which matters when Temporal
    re-dispatches an activity whose previous attempt is still draining. It is zero-padded because the kill
    matches the id as a LIKE prefix, where an unpadded "1" would also match attempt 12.

    `get_live_query_progress` matches on the recalculation id, which sits before this suffix, so its prefix
    still matches.
    """
    return f"experiment_metric_recalc_{recalculation_id}_{metric_uuid}_attempt{attempt:02d}"


@database_sync_to_async_pool(executor=_CANCELLATION_EXECUTOR)
def _cancel_metric_query_sync(recalculation_id: str, metric_uuid: str, attempt: int) -> None:
    """Kill the ClickHouse query the metric's calc left running, so the abandoned attempt stops reading."""
    close_old_connections()
    state = run_state._get_recalc_state(recalculation_id)
    # This runs in its own thread, so it inherits none of the calc body's tags. Untagged statements raise in
    # local dev and log a stack trace each in production.
    with tags_context(
        trigger="warming/experiment_metrics_recalculation",
        team_id=state.team_id,
        product=Product.EXPERIMENTS,
        feature=Feature.CACHE_WARMUP,
    ):
        cancel_query_on_cluster(state.team_id, _client_query_id(recalculation_id, metric_uuid, attempt))


def _calculate_experiment_metric_for_recalculation_sync(
    experiment_id: int,
    metric_uuid: str,
    recalculation_id: str,
    query_to: str,
    role: str = "primary",
    is_final_attempt: bool = True,
    attempt: int = 1,
    precomputation_mode: PrecomputationMode | None = None,
    calculation_key_version: int = 1,
    task_queue: str = "",
) -> MetricRecalculationResult:
    close_old_connections()

    try:
        query_to_dt = datetime.fromisoformat(query_to)
    except ValueError as e:
        raise ApplicationError(
            f"query_to {query_to!r} is not a valid ISO datetime string: {e}",
            type="invalid_input",
            non_retryable=True,
        )
    state = run_state._get_recalc_state(recalculation_id)

    # Defense-in-depth at the activity boundary: the workflow constructs all four args from its own state,
    # so a mismatch here means a workflow bug, not a data issue. Fail non-retryable so Temporal terminates
    # the run promptly rather than burning retries on a deterministic failure.
    if experiment_id != state.experiment_id:
        raise ApplicationError(
            f"experiment_id {experiment_id} does not match recalc.experiment_id {state.experiment_id}",
            type="input_mismatch",
            non_retryable=True,
        )
    if metric_uuid not in state.metric_uuids:
        raise ApplicationError(
            f"metric_uuid {metric_uuid} is not in recalc {recalculation_id}'s metric set",
            type="input_mismatch",
            non_retryable=True,
        )
    if state.query_to is None:
        raise ApplicationError(
            f"recalc {recalculation_id} has no query_to set — calculate activity ran before start activity",
            type="invalid_state",
            non_retryable=True,
        )
    if query_to_dt != state.query_to:
        raise ApplicationError(
            f"query_to {query_to_dt.isoformat()} does not match recalc.query_to {state.query_to.isoformat()}",
            type="input_mismatch",
            non_retryable=True,
        )

    with team_scope(state.team_id, canonical=True):
        try:
            experiment = Experiment.objects.get(id=experiment_id, deleted=False)
        except Experiment.DoesNotExist:
            return attempt_records._fail(
                recalculation_id,
                metric_uuid,
                "discovery",
                f"Experiment {experiment_id} not found or deleted",
                error_type="validation_error",
                calculation_key=None,
            )

        # One read of the settings serves the reuse check, the query and the write, so the result is filed under the key
        # of the settings it was computed from.
        team_config = team_experiments_configs([experiment.team_id])[experiment.team_id]
        calculation_config = get_metric_calculation_config(
            experiment, metric_uuid, team_config=team_config, key_version=calculation_key_version
        )
        if calculation_config is None:
            return attempt_records._fail(
                recalculation_id,
                metric_uuid,
                "discovery",
                f"Metric {metric_uuid} not found in experiment {experiment_id}",
                error_type="validation_error",
                calculation_key=None,
            )
        metric_dict = calculation_config.definition

        if not experiment.start_date:
            return attempt_records._fail(
                recalculation_id,
                metric_uuid,
                "discovery",
                f"Experiment {experiment_id} has no start_date",
                error_type="validation_error",
                calculation_key=None,
            )

        # Computed before any failure path, so an error here can't mask the error that the failure path records.
        calculation_key = calculation_config.calculation_key()
        results = MetricResultStore(experiment_id=experiment_id)

        # Skip the query if this metric is already computed for this exact config and window; a config change
        # changes the fingerprint, so a stale result won't match and recomputes.
        if results.has_completed(calculation_config, window=query_to_dt):
            # A crash between the result write and the retry cleanup on a prior attempt lands here on the
            # next one; clear so a completed metric can't keep reporting as retrying.
            attempt_records._clear_retry(recalculation_id, metric_uuid)
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        client_query_id = _client_query_id(recalculation_id, metric_uuid, attempt)

        calc_started_at = time.perf_counter()
        query_from = experiment.start_date

        runner: ExperimentQueryRunner | None = None

        def record_terminal_error(message: str, error_type: str, *, retriable: bool) -> None:
            results.record_run_failure(
                recalculation_id,
                calculation_config,
                window=query_to_dt,
                query_from=query_from,
                error_message=message,
                query_id=client_query_id,
            )
            attempt_records._record_failure(
                recalculation_id,
                metric_uuid,
                "calculation",
                message,
                error_type=error_type,
                retriable=retriable,
                calculation_key=calculation_key,
                exposures_path=runner.exposures_path if runner is not None else None,
            )
            analytics._capture_experiment_metric_event(
                experiment,
                metric_uuid,
                role,
                metric_dict,
                "experiment metric error",
                {
                    "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                    "error_type": error_type,
                    "error_message": message,
                },
                trigger=state.trigger,
            )

        try:
            runner = ExperimentQueryRunner(
                query=ExperimentQuery(
                    experiment_id=experiment_id,
                    metric=build_metric(metric_dict),
                    precomputation_mode=precomputation_mode,
                ),
                team=experiment.team,
                as_of=query_to_dt,
                workload=Workload.OFFLINE,
                # Userless background recompute. Warehouse access is enforced when the metric is authored,
                # so resolve warehouse tables here instead of failing closed.
                bypass_warehouse_access_control=True,
                # Internal caller: keep exceptions raw so the except branches below see the original types
                # (StatisticError must not arrive pre-converted to ValidationError), and keep the runner's
                # own error event silent — this activity emits the terminal event itself, on the final attempt.
                user_facing=False,
                error_event_context=None,
                # Must fail typed inside the activity before Temporal's start_to_close kill — see models.py.
                max_execution_time=METRIC_CALC_MAX_EXECUTION_TIME_SECONDS,
                experiment=experiment,
                team_experiments_config=team_config,
            )

            # Attribute CH load back to this team + product so query_log analysis can tell whose recalc is
            # expensive without reverse-engineering the trigger string.
            with tags_context(
                trigger="warming/experiment_metrics_recalculation",
                team_id=state.team_id,
                product=Product.EXPERIMENTS,
                feature=Feature.CACHE_WARMUP,
                client_query_id=client_query_id,
                # Also covers the precompute inserts, which run inside this context.
                ch_user=recalculation_clickhouse_user(task_queue),
            ):
                result = runner.run(execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS)
            result_dict = sanitize_non_finite(result.model_dump(mode="json"))

            with transaction.atomic():
                stored = results.record_run_result(
                    recalculation_id,
                    calculation_config,
                    window=query_to_dt,
                    query_from=query_from,
                    result=result_dict,
                    query_id=client_query_id,
                )
                # The workflow can record this metric as out of time while this attempt's thread still runs. The
                # frontend shows a metric_errors entry over a result, so a result that lands later removes it.
                if stored:
                    attempt_records._clear_error(recalculation_id, metric_uuid)
            analytics._capture_experiment_metric_event(
                experiment,
                metric_uuid,
                role,
                metric_dict,
                "experiment metric finished",
                {"duration_ms": round((time.perf_counter() - calc_started_at) * 1000)},
                trigger=state.trigger,
            )
            attempt_records._clear_retry(recalculation_id, metric_uuid)
            return MetricRecalculationResult(metric_uuid=metric_uuid, success=True)

        except (StatisticError, ZeroDivisionError) as e:
            # Expected "not enough data" style failures — warn, no exception capture.
            message = str(e)[: attempt_records._MAX_ERROR_MESSAGE_LENGTH]
            results.record_run_failure(
                recalculation_id,
                calculation_config,
                window=query_to_dt,
                query_from=query_from,
                error_message=message,
                query_id=client_query_id,
            )
            logger.warning(
                "Experiment metric recalculation failed due to insufficient data",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                error=message,
            )
            analytics._capture_experiment_metric_event(
                experiment,
                metric_uuid,
                role,
                metric_dict,
                "experiment metric error",
                {
                    "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                    "error_type": "insufficient_data",
                    "error_message": message,
                },
                trigger=state.trigger,
            )
            return attempt_records._fail(
                recalculation_id,
                metric_uuid,
                "calculation",
                message,
                error_type="insufficient_data",
                calculation_key=calculation_key,
            )

        except (ConcurrencyLimitExceeded, ClickHouseAtCapacity) as e:
            message = str(e)[: attempt_records._MAX_ERROR_MESSAGE_LENGTH]
            retry_delay_seconds = attempt_records._capacity_retry_delay_seconds(attempt)
            capacity_attempts_exhausted = attempt >= CAPACITY_MAX_METRIC_ATTEMPTS
            is_last_attempt = is_final_attempt or capacity_attempts_exhausted
            if is_last_attempt:
                record_terminal_error(message, classify_experiment_query_error(e), retriable=True)
            logger.warning(
                "Experiment metric recalculation deferred by ClickHouse backpressure",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                is_final_attempt=is_last_attempt,
                error_class=type(e).__name__,
            )
            if is_last_attempt:
                attempt_records._clear_retry(recalculation_id, metric_uuid)
            else:
                # Exact, not estimated: this branch sets the delay explicitly via next_retry_delay.
                error_type = classify_experiment_query_error(e)
                safe_message = attempt_records._safe_retry_message(e, error_type)
                attempt_records._record_retry(
                    recalculation_id,
                    metric_uuid,
                    attempt,
                    CAPACITY_MAX_METRIC_ATTEMPTS,
                    error_type,
                    safe_message,
                    retry_delay_seconds,
                    calculation_key=calculation_key,
                )
                analytics._capture_experiment_metric_event(
                    experiment,
                    metric_uuid,
                    role,
                    metric_dict,
                    "experiment metric retry",
                    {
                        "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                        "error_type": error_type,
                        "error_message": safe_message,
                        "attempt": attempt,
                        "max_attempts": CAPACITY_MAX_METRIC_ATTEMPTS,
                        "next_retry_delay_seconds": round(retry_delay_seconds, 1),
                    },
                    trigger=state.trigger,
                )
            raise ApplicationError(
                message,
                type=type(e).__name__,
                next_retry_delay=timedelta(seconds=retry_delay_seconds),
                non_retryable=capacity_attempts_exhausted,
            ) from e

        except Exception as e:
            message = str(e)[: attempt_records._MAX_ERROR_MESSAGE_LENGTH]
            error_type = classify_experiment_query_error(e)
            is_permanent = error_type in NON_RETRYABLE_ERROR_TYPES or isinstance(e, ValueError)
            max_attempts = TIMEOUT_MAX_METRIC_ATTEMPTS if error_type == "timeout" else MAX_METRIC_ATTEMPTS
            is_last_attempt = is_final_attempt or attempt >= max_attempts
            # validation_error = the user's metric config is broken (e.g. HogQL referencing a
            # column outside an aggregate) — a stored failure, not a platform error to track.
            if error_type != "validation_error":
                capture_exception(
                    e,
                    additional_properties={
                        "experiment_id": experiment_id,
                        "metric_uuid": metric_uuid,
                        "recalculation_id": recalculation_id,
                    },
                )
            if is_last_attempt or is_permanent:
                record_terminal_error(message, error_type, retriable=not is_permanent)
            logger.exception(
                "Experiment metric recalculation failed",
                experiment_id=experiment_id,
                metric_uuid=metric_uuid,
                is_final_attempt=is_last_attempt,
                error_type=error_type,
            )
            if is_last_attempt or is_permanent:
                attempt_records._clear_retry(recalculation_id, metric_uuid)
            else:
                retry_delay_seconds = attempt_records._estimated_retry_delay_seconds(attempt)
                safe_message = attempt_records._safe_retry_message(e, error_type)
                attempt_records._record_retry(
                    recalculation_id,
                    metric_uuid,
                    attempt,
                    max_attempts,
                    error_type,
                    safe_message,
                    retry_delay_seconds,
                    calculation_key=calculation_key,
                )
                analytics._capture_experiment_metric_event(
                    experiment,
                    metric_uuid,
                    role,
                    metric_dict,
                    "experiment metric retry",
                    {
                        "duration_ms": round((time.perf_counter() - calc_started_at) * 1000),
                        "error_type": error_type,
                        "error_message": safe_message,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "next_retry_delay_seconds": retry_delay_seconds,
                    },
                    trigger=state.trigger,
                )
            if is_permanent:
                if error_type == "validation_error":
                    # The activity interceptor captures any ApplicationError that escapes, which
                    # would undo the capture skip above. The non-reportable variant keeps the
                    # stored failure out of error tracking.
                    raise NonReportableApplicationError(message, type=error_type, non_retryable=True) from e
                raise ApplicationError(message, type=error_type, non_retryable=True) from e
            if is_last_attempt and not is_final_attempt:
                # The error class cap is below MAX_METRIC_ATTEMPTS, so stop the RetryPolicy from retrying further.
                raise ApplicationError(message, type=error_type, non_retryable=True) from e
            raise


@database_sync_to_async_pool
def _record_metric_out_of_time_failure_sync(failure: MetricOutOfTimeFailure) -> None:
    close_old_connections()
    state = run_state._get_recalc_state(failure.recalculation_id)

    with team_scope(state.team_id, canonical=True):
        # A final attempt that ran to the end already persisted its own failure, with the real error type.
        if ExperimentMetricsRecalculation.objects.filter(
            id=failure.recalculation_id, metric_errors__has_key=failure.metric_uuid
        ).exists():
            return

        experiment = Experiment.objects.filter(id=failure.experiment_id, deleted=False).first()
        calculation_config = (
            get_metric_calculation_config(experiment, failure.metric_uuid, key_version=failure.calculation_key_version)
            if experiment
            else None
        )
        if experiment is None or calculation_config is None or not experiment.start_date or state.query_to is None:
            attempt_records._fail(
                failure.recalculation_id,
                failure.metric_uuid,
                "calculation",
                _OUT_OF_TIME_MESSAGE,
                error_type="timeout",
                calculation_key=None,
            )
            return

        calculation_key = calculation_config.calculation_key()
        results = MetricResultStore(experiment_id=experiment.id)
        with transaction.atomic():
            # The last attempt can write its result and die before it reports success, which Temporal sees as a
            # timeout. Its thread can also still be running. Take the result store's run-write locks, in its order,
            # so that no result write lands between this check and the two failure writes.
            Experiment.objects.select_for_update(no_key=True).filter(id=experiment.id, team_id=state.team_id).exists()
            ExperimentMetricsRecalculation.objects.select_for_update().filter(id=failure.recalculation_id).exists()
            completed = results.has_completed(calculation_config, window=state.query_to)
            if not completed:
                results.record_run_failure(
                    failure.recalculation_id,
                    calculation_config,
                    window=state.query_to,
                    query_from=experiment.start_date,
                    error_message=_OUT_OF_TIME_MESSAGE,
                    query_id=None,
                )
                attempt_records._record_failure(
                    failure.recalculation_id,
                    failure.metric_uuid,
                    "calculation",
                    _OUT_OF_TIME_MESSAGE,
                    error_type="timeout",
                    retriable=True,
                    calculation_key=calculation_key,
                )
        if completed:
            attempt_records._clear_retry(failure.recalculation_id, failure.metric_uuid)
            return

        attempt_records._clear_retry(failure.recalculation_id, failure.metric_uuid)
        analytics._capture_experiment_metric_event(
            experiment,
            failure.metric_uuid,
            failure.role,
            calculation_config.definition,
            "experiment metric error",
            {"error_type": "timeout", "error_message": _OUT_OF_TIME_MESSAGE},
            trigger=state.trigger,
        )
