"""Per-metric attempt records on a recalculation row: failures, retries, their delays and the stored messages."""

import random
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from products.experiments.backend.facade.enums import ExposuresPath
from products.experiments.backend.hogql_queries.error_handling import get_user_friendly_message
from products.experiments.backend.models.experiment import ExperimentMetricsRecalculation
from products.experiments.backend.recalculation.payloads import RUN_ENTRY_CALCULATION_KEY
from products.experiments.backend.temporal.models import (
    CAPACITY_RETRY_BACKOFF_COEFFICIENT,
    CAPACITY_RETRY_FIRST_DELAY_MAX_SECONDS,
    CAPACITY_RETRY_FIRST_DELAY_MIN_SECONDS,
    CAPACITY_RETRY_MAX_DELAY_SECONDS,
    RECALCULATION_RETRY_BACKOFF_COEFFICIENT,
    RECALCULATION_RETRY_INITIAL_INTERVAL_SECONDS,
    RECALCULATION_RETRY_MAX_INTERVAL_SECONDS,
    MetricRecalculationResult,
)

# Cap stored/returned error messages so a pathological traceback can't bloat the Temporal payload (~2 MiB cap).
_MAX_ERROR_MESSAGE_LENGTH = 2000


def _record_failure(
    recalculation_id: str,
    metric_uuid: str,
    step: str,
    message: str,
    *,
    error_type: str,
    retriable: bool,
    calculation_key: str | None,
    exposures_path: ExposuresPath | None = None,
) -> None:
    """Merge the error entry into metric_errors under a row lock (no lost updates between concurrent failures).

    Idempotent on Temporal retries: the dict is keyed by metric_uuid, so re-running this for the same metric
    just overwrites the existing entry with a fresh timestamp. retriable is True only when a transient error
    exhausted its attempts, so the frontend heals that metric on page load and leaves the rest to a user retry.
    `calculation_key` is the key of the config that failed, in the key version of the run. Reads of the run serve the
    entry only while the current config gives that key in some key version (`entries_of_current_configs`). A failure
    without a config passes None, and reads then serve its message only when its step or error type holds fixed text.
    """
    capped = message[:_MAX_ERROR_MESSAGE_LENGTH]
    with transaction.atomic():
        recalc = ExperimentMetricsRecalculation.objects.select_for_update().get(id=recalculation_id)
        metric_errors = recalc.metric_errors or {}
        metric_errors[metric_uuid] = {
            "step": step,
            "message": capped,
            "error_type": error_type,
            "retriable": retriable,
            RUN_ENTRY_CALCULATION_KEY: calculation_key,
            "timestamp": timezone.now().isoformat(),
        }
        if exposures_path is not None:
            metric_errors[metric_uuid]["exposures_path"] = exposures_path.value
        recalc.metric_errors = metric_errors
        recalc.save(update_fields=["metric_errors"])


def _estimated_retry_delay_seconds(attempt: int) -> float:
    """Mirror of the workflow's RetryPolicy backoff for the attempt that just failed."""
    return min(
        RECALCULATION_RETRY_INITIAL_INTERVAL_SECONDS * RECALCULATION_RETRY_BACKOFF_COEFFICIENT ** (attempt - 1),
        RECALCULATION_RETRY_MAX_INTERVAL_SECONDS,
    )


def _capacity_retry_delay_seconds(attempt: int) -> float:
    """Random delay in the band for the attempt that just failed. The band doubles per attempt, up to the cap."""
    growth = CAPACITY_RETRY_BACKOFF_COEFFICIENT ** (max(attempt, 1) - 1)
    return random.uniform(
        min(CAPACITY_RETRY_FIRST_DELAY_MIN_SECONDS * growth, CAPACITY_RETRY_MAX_DELAY_SECONDS),
        min(CAPACITY_RETRY_FIRST_DELAY_MAX_SECONDS * growth, CAPACITY_RETRY_MAX_DELAY_SECONDS),
    )


_RETRY_SAFE_MESSAGES: dict[str, str] = {
    "rate_limited": "The query was deferred because the cluster is at capacity.",
    "timeout": "The query timed out.",
    "out_of_memory": "The query ran out of memory.",
    "byte_limit": "The query read too much data.",
    "server_error": "The query failed with a server error.",
}


def _safe_retry_message(error: Exception, error_type: str) -> str:
    """Raw exception text can embed the executed query, including substituted warehouse credentials
    (``calculation`` runs the runner with user_facing=False, which keeps exceptions raw), and metric_retries
    is visible to anyone with experiment read access. Persist only type-derived copy; the raw error
    stays in logs and error tracking."""
    return get_user_friendly_message(error) or _RETRY_SAFE_MESSAGES.get(
        error_type, _RETRY_SAFE_MESSAGES["server_error"]
    )


def _record_retry(
    recalculation_id: str,
    metric_uuid: str,
    attempt: int,
    max_attempts: int,
    error_type: str,
    message: str,
    delay_seconds: float,
    *,
    calculation_key: str,
) -> None:
    """Transient attempt state for the UI, keyed by metric_uuid; overwritten per attempt, removed by the
    metric's terminal write. Carries a user-safe description of the error that triggered the retry;
    next_retry_at is an estimate (worker pickup adds slack after it passes). `calculation_key` is as in
    `_record_failure`."""
    with transaction.atomic():
        recalc = ExperimentMetricsRecalculation.objects.select_for_update().get(id=recalculation_id)
        metric_retries = recalc.metric_retries or {}
        metric_retries[metric_uuid] = {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "error_type": error_type,
            "message": message[:_MAX_ERROR_MESSAGE_LENGTH],
            "next_retry_at": (timezone.now() + timedelta(seconds=delay_seconds)).isoformat(),
            RUN_ENTRY_CALCULATION_KEY: calculation_key,
        }
        recalc.metric_retries = metric_retries
        recalc.save(update_fields=["metric_retries"])


def _clear_retry(recalculation_id: str, metric_uuid: str) -> None:
    with transaction.atomic():
        recalc = ExperimentMetricsRecalculation.objects.select_for_update().get(id=recalculation_id)
        if metric_uuid in (recalc.metric_retries or {}):
            recalc.metric_retries.pop(metric_uuid)
            recalc.save(update_fields=["metric_retries"])


def _clear_error(recalculation_id: str, metric_uuid: str) -> None:
    with transaction.atomic():
        recalc = ExperimentMetricsRecalculation.objects.select_for_update().get(id=recalculation_id)
        if metric_uuid in (recalc.metric_errors or {}):
            recalc.metric_errors.pop(metric_uuid)
            recalc.save(update_fields=["metric_errors"])


def _fail(
    recalculation_id: str,
    metric_uuid: str,
    step: str,
    message: str,
    *,
    error_type: str,
    calculation_key: str | None,
) -> MetricRecalculationResult:
    """Record a permanent failure on the job (lookup step: job-only; calculation step: also persists a result row upstream)."""
    _record_failure(
        recalculation_id,
        metric_uuid,
        step,
        message,
        error_type=error_type,
        retriable=False,
        calculation_key=calculation_key,
    )
    _clear_retry(recalculation_id, metric_uuid)
    return MetricRecalculationResult(
        metric_uuid=metric_uuid, success=False, error_step=step, error_message=message[:_MAX_ERROR_MESSAGE_LENGTH]
    )
