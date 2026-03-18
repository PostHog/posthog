import time
import datetime as dt
from collections.abc import Mapping

from temporalio import activity
from temporalio.common import MetricMeter

Attributes = dict[str, str | int | float | bool]

TASKS_LATENCY_HISTOGRAM_METRICS = ("tasks_process_sandbox_step_latency",)
TASKS_LATENCY_HISTOGRAM_BUCKETS = [
    100.0,
    250.0,
    500.0,
    1_000.0,
    5_000.0,
    10_000.0,
    30_000.0,
    60_000.0,
    120_000.0,
    300_000.0,
    600_000.0,
    1_800_000.0,
    3_600_000.0,
]


def _metric_meter(additional_attributes: Mapping[str, str | int | float | bool] | None = None) -> MetricMeter:
    if not activity.in_activity():
        raise RuntimeError("Tasks metrics can only be emitted inside a Temporal activity")

    meter = activity.metric_meter()
    if additional_attributes:
        meter = meter.with_additional_attributes(dict(additional_attributes))

    return meter


def _bool_label(value: bool | None) -> str:
    if value is None:
        return "unknown"
    return "true" if value else "false"


def increment_snapshot_usage(used_snapshot: bool) -> None:
    meter = _metric_meter({"used_snapshot": _bool_label(used_snapshot)})
    meter.create_counter(
        "tasks_process_snapshot_usage",
        "Number of process-task runs by snapshot usage",
    ).add(1)


class StepTimer:
    def __init__(self, step: str, used_snapshot: bool | None = None) -> None:
        self.step = step
        self.used_snapshot = used_snapshot
        self._start_counter: float | None = None

    def set_used_snapshot(self, used_snapshot: bool) -> None:
        self.used_snapshot = used_snapshot

    def __enter__(self) -> "StepTimer":
        self._start_counter = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._start_counter is None:
            raise RuntimeError("StepTimer used without calling __enter__")

        delta_ms = int((time.perf_counter() - self._start_counter) * 1000)
        delta = dt.timedelta(milliseconds=delta_ms)

        attributes: Attributes = {
            "step": self.step,
            "used_snapshot": _bool_label(self.used_snapshot),
            "status": "FAILED" if exc_value is not None else "COMPLETED",
        }

        try:
            _metric_meter(attributes).create_histogram_timedelta(
                "tasks_process_sandbox_step_latency",
                "Latency for get_sandbox_for_repository sub-steps",
                unit="ms",
            ).record(delta)
        except Exception:
            pass

        self._start_counter = None
