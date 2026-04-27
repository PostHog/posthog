"""Prometheus metrics and Temporal interceptor for logs alerting."""

import time
import typing
import datetime as dt

from django.conf import settings

from temporalio import activity, workflow
from temporalio.common import MetricMeter
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from posthog.temporal.common.logger import get_write_only_logger

from products.logs.backend.alert_error_classifier import AlertErrorCode
from products.logs.backend.alert_state_machine import AlertState, NotificationAction

logger = get_write_only_logger(__name__)

_NOTIFICATION_FAILURE_LABELS: dict[NotificationAction, str] = {
    NotificationAction.FIRE: "firing",
    NotificationAction.RESOLVE: "resolved",
}

ALERTING_ACTIVITY_TYPES = frozenset(
    {
        "check_alerts_activity",
    }
)

Attributes = dict[str, str | int | float | bool]

LOGS_ALERTING_LATENCY_HISTOGRAM_METRICS = (
    "logs_alerting_check_duration_ms",
    "logs_alerting_cycle_duration_ms",
    "logs_alerting_scheduler_lag_ms",
    "logs_alerting_schedule_to_start_ms",
)

LOGS_ALERTING_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,
    500.0,
    1_000.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    120_000.0,
    300_000.0,
]


def get_metric_meter(additional_attributes: Attributes | None = None) -> MetricMeter:
    """Return a meter depending on whether we are in an activity or workflow context."""
    if activity.in_activity():
        meter = activity.metric_meter()
    elif workflow.in_workflow():
        meter = workflow.metric_meter()
    else:
        raise RuntimeError("Not within workflow or activity context")

    if additional_attributes:
        meter = meter.with_additional_attributes(additional_attributes)

    return meter


def _record_histogram(name: str, description: str, duration_ms: int, attributes: Attributes | None = None) -> None:
    meter = get_metric_meter(attributes)
    hist = meter.create_histogram_timedelta(name=name, description=description, unit="ms")
    hist.record(dt.timedelta(milliseconds=duration_ms))


AlertOutcome = typing.Literal["ok", "fired", "resolved", "errored"]


def increment_checks_total(outcome: AlertOutcome) -> None:
    """Increment per-alert check counter."""
    meter = get_metric_meter({"outcome": outcome})
    counter = meter.create_counter("logs_alerting_checks_total", "Number of individual alert checks by outcome")
    counter.add(1)


def increment_check_errors(category: AlertErrorCode) -> None:
    meter = get_metric_meter({"category": category})
    counter = meter.create_counter(
        "logs_alerting_check_errors_total",
        "Errored alert checks broken down by classifier category",
    )
    counter.add(1)


def increment_notification_failures(action: NotificationAction) -> None:
    label = _NOTIFICATION_FAILURE_LABELS[action]
    meter = get_metric_meter({"event": label})
    counter = meter.create_counter(
        "logs_alerting_notification_failures_total",
        "Kafka produce failures for firing/resolved notifications",
    )
    counter.add(1)


def increment_state_transition(from_state: AlertState, to_state: AlertState) -> None:
    meter = get_metric_meter({"from": from_state.value, "to": to_state.value})
    counter = meter.create_counter(
        "logs_alerting_state_transitions_total",
        "Alert state transitions by from/to state (worker-committed)",
    )
    counter.add(1)


def record_alerts_active(count: int) -> None:
    meter = get_metric_meter()
    gauge = meter.create_gauge(
        "logs_alerting_alerts_active",
        "Number of due alerts evaluated this cycle",
    )
    gauge.set(count)


def record_checkpoint_lag(now: dt.datetime, checkpoint: dt.datetime) -> None:
    meter = get_metric_meter()
    gauge = meter.create_gauge(
        "logs_alerting_ingestion_checkpoint_lag_seconds",
        "Wall-clock age of the logs-ingestion checkpoint used to anchor alert windows",
    )
    lag_seconds = max(0, int((now - checkpoint).total_seconds()))
    gauge.set(lag_seconds)


def increment_checkpoint_unavailable() -> None:
    meter = get_metric_meter()
    counter = meter.create_counter(
        "logs_alerting_checkpoint_unavailable_total",
        "Cycles where the logs-ingestion checkpoint could not be resolved (no alerts due, or fetch failure)",
    )
    counter.add(1)


def record_check_duration(duration_ms: int) -> None:
    _record_histogram("logs_alerting_check_duration_ms", "Per-alert evaluation duration", duration_ms)


def record_scheduler_lag(lag_ms: int) -> None:
    _record_histogram("logs_alerting_scheduler_lag_ms", "Delay between alert due time and actual check time", lag_ms)


def record_schedule_to_start_latency(activity_type: str, latency_ms: int) -> None:
    _record_histogram(
        "logs_alerting_schedule_to_start_ms",
        "Time between activity scheduling and start",
        latency_ms,
        {"activity_type": activity_type},
    )


# TODO: Extract ExecutionTimeRecorder to posthog/temporal/common/ — copied from
# posthog/temporal/llm_analytics/metrics.py to avoid cross-product import.
class ExecutionTimeRecorder:
    """Context manager to record execution time to a histogram metric."""

    def __init__(
        self,
        histogram_name: str,
        /,
        description: str | None = None,
        histogram_attributes: Attributes | None = None,
    ) -> None:
        self.histogram_name = histogram_name
        self.description = description
        self.histogram_attributes = histogram_attributes or {}
        self._start_counter: float | None = None

    def __enter__(self) -> typing.Self:
        self._start_counter = time.perf_counter()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: object
    ) -> None:
        if self._start_counter is None:
            raise RuntimeError("Start counter not initialized, did you call `__enter__`?")

        end_counter = time.perf_counter()
        delta_ms = int((end_counter - self._start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_ms)

        attributes = dict(self.histogram_attributes)
        if exc_value is not None:
            attributes["status"] = "FAILED"
        else:
            attributes["status"] = "COMPLETED"

        meter = get_metric_meter(attributes)
        hist = meter.create_histogram_timedelta(name=self.histogram_name, description=self.description, unit="ms")
        try:
            hist.record(value=delta)
        except Exception:
            logger.exception("Failed to record execution time to histogram '%s'", self.histogram_name)


class LogsAlertingMetricsInterceptor(Interceptor):
    """Interceptor to emit Prometheus metrics for logs alerting workflows."""

    task_queue = settings.LOGS_ALERTING_TASK_QUEUE

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _LogsAlertingActivityInterceptor(super().intercept_activity(next))


class _LogsAlertingActivityInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> typing.Any:
        activity_info = activity.info()
        activity_type = activity_info.activity_type

        if activity_type not in ALERTING_ACTIVITY_TYPES:
            return await super().execute_activity(input)

        scheduled_time = activity_info.scheduled_time
        started_time = activity_info.started_time
        if scheduled_time and started_time:
            schedule_to_start_ms = int((started_time - scheduled_time).total_seconds() * 1000)
            record_schedule_to_start_latency(activity_type, schedule_to_start_ms)

        with ExecutionTimeRecorder(
            "logs_alerting_cycle_duration_ms",
            description="Full alert check cycle duration",
            histogram_attributes={"activity_type": activity_type},
        ):
            return await super().execute_activity(input)
