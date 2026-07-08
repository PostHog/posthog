import time
import datetime as dt
from collections.abc import Mapping

from temporalio import activity
from temporalio.common import MetricMeter

Attributes = dict[str, str | int | float | bool]

TASKS_LATENCY_HISTOGRAM_METRICS = (
    "tasks_process_sandbox_step_latency",
    "tasks_process_snapshot_create_latency",
    "tasks_boot_total_latency",
)
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


def increment_snapshot_usage(
    used_snapshot: bool,
    *,
    snapshot_source: str = "unknown",
    snapshot_kind: str = "unknown",
) -> None:
    try:
        meter = _metric_meter(
            {
                "used_snapshot": _bool_label(used_snapshot),
                "snapshot_source": snapshot_source,
                "snapshot_kind": snapshot_kind,
            }
        )
        meter.create_counter(
            "tasks_process_snapshot_usage",
            "Number of process-task runs by final snapshot usage",
        ).add(1)
    except Exception:
        pass


def increment_snapshot_restore(snapshot_source: str, snapshot_kind: str, outcome: str) -> None:
    try:
        meter = _metric_meter(
            {
                "snapshot_source": snapshot_source,
                "snapshot_kind": snapshot_kind,
                "outcome": outcome,
            }
        )
        meter.create_counter(
            "tasks_process_snapshot_restore",
            "Snapshot restore outcomes for process-task sandbox creation",
        ).add(1)
    except Exception:
        pass


def increment_snapshot_create(snapshot_kind: str, outcome: str) -> None:
    try:
        meter = _metric_meter({"snapshot_kind": snapshot_kind, "outcome": outcome})
        meter.create_counter(
            "tasks_process_snapshot_create",
            "Resume snapshot creation outcomes for process-task runs",
        ).add(1)
    except Exception:
        pass


def record_snapshot_create_latency_ms(snapshot_kind: str, outcome: str, latency_ms: int) -> None:
    try:
        delta = dt.timedelta(milliseconds=latency_ms)
        _metric_meter({"snapshot_kind": snapshot_kind, "outcome": outcome}).create_histogram_timedelta(
            "tasks_process_snapshot_create_latency",
            "Resume snapshot creation latency for process-task runs",
            unit="ms",
        ).record(delta)
    except Exception:
        pass


def increment_credential_refresh(kind: str, outcome: str) -> None:
    """Record a sandbox credential refresh outcome.

    outcome is one of: refreshed (token re-injected), skipped (nothing to do or
    token could not be resolved), failed (the credential raised), orphaned (the
    credential can never be refreshed again this run — integration deleted or
    user re-auth required). Best-effort: a metric failure must never break the
    refresh loop.
    """
    try:
        meter = _metric_meter({"kind": kind, "outcome": outcome})
        meter.create_counter(
            "tasks_sandbox_credential_refresh",
            "Sandbox credential refresh outcomes for running cloud task runs",
        ).add(1)
    except Exception:
        pass


def increment_sandbox_created(runtime: str) -> None:
    """Record a sandbox creation, labeled by runtime ("vm" or "gvisor")."""
    try:
        meter = _metric_meter({"runtime": runtime})
        meter.create_counter(
            "tasks_process_sandbox_created",
            "Sandboxes created for process-task runs by runtime",
        ).add(1)
    except Exception:
        pass


def record_agent_server_session_init_ms(session_init_ms: int, boot_path: str | None = None) -> None:
    try:
        attributes: Attributes = {
            "step": "agent_server_session_init",
            "status": "COMPLETED",
        }
        if boot_path is not None:
            attributes["boot_path"] = boot_path
        _metric_meter(attributes).create_histogram_timedelta(
            "tasks_process_sandbox_step_latency",
            "Latency for get_sandbox_for_repository sub-steps",
            unit="ms",
        ).record(dt.timedelta(milliseconds=session_init_ms))
    except Exception:
        pass


def record_boot_total_ms(
    boot_total_ms: int,
    *,
    boot_path: str,
    used_snapshot: bool | None,
    has_repo: bool,
    origin_product: str | None,
) -> None:
    """Wall-clock time from workflow start to agent-server ready, the boot headline number.

    Recorded once per successful boot by the activity that completes it. `boot_path`
    distinguishes the serial launch ("classic"), the launch-before-clone overlap
    ("overlap"), and future boot architectures, so rollouts can be compared per cohort.
    """
    try:
        attributes: Attributes = {
            "boot_path": boot_path,
            "used_snapshot": _bool_label(used_snapshot),
            "has_repo": _bool_label(has_repo),
            "origin_product": origin_product or "unknown",
        }
        _metric_meter(attributes).create_histogram_timedelta(
            "tasks_boot_total_latency",
            "Wall-clock latency from workflow start to agent-server ready",
            unit="ms",
        ).record(dt.timedelta(milliseconds=boot_total_ms))
    except Exception:
        pass


class StepTimer:
    def __init__(self, step: str, used_snapshot: bool | None = None, boot_path: str | None = None) -> None:
        self.step = step
        self.used_snapshot = used_snapshot
        self.boot_path = boot_path
        # Elapsed wall-clock of the step, readable after the context exits so callers
        # can thread the same number into activity outputs / analytics events.
        self.elapsed_ms: int | None = None
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
        self.elapsed_ms = delta_ms
        delta = dt.timedelta(milliseconds=delta_ms)

        attributes: Attributes = {
            "step": self.step,
            "used_snapshot": _bool_label(self.used_snapshot),
            "status": "FAILED" if exc_value is not None else "COMPLETED",
        }
        if self.boot_path is not None:
            attributes["boot_path"] = self.boot_path

        try:
            _metric_meter(attributes).create_histogram_timedelta(
                "tasks_process_sandbox_step_latency",
                "Latency for get_sandbox_for_repository sub-steps",
                unit="ms",
            ).record(delta)
        except Exception:
            pass

        self._start_counter = None
