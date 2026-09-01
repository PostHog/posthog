import os
import time
import datetime as dt
from collections.abc import Mapping
from typing import Any

import posthoganalytics
from temporalio import activity, workflow
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
    15_000.0,
    20_000.0,
    30_000.0,
    45_000.0,
    60_000.0,
    90_000.0,
    120_000.0,
    180_000.0,
    300_000.0,
    600_000.0,
    1_800_000.0,
    3_600_000.0,
]

TASKS_RUN_TOKENS_HISTOGRAM_METRICS = ("tasks_run_total_tokens",)
TASKS_RUN_TOKENS_HISTOGRAM_BUCKETS = [
    10_000.0,
    50_000.0,
    100_000.0,
    250_000.0,
    500_000.0,
    1_000_000.0,
    2_500_000.0,
    5_000_000.0,
    10_000_000.0,
    25_000_000.0,
    50_000_000.0,
    100_000_000.0,
]

_RUN_TOKEN_KINDS = {
    "input": "input_tokens",
    "output": "output_tokens",
    "cache_read": "cache_read_tokens",
    "cache_write": "cache_write_tokens",
    "thought": "thought_tokens",
}


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


_ALLOWED_RUNTIME_ADAPTERS = {"claude", "codex"}


def sandbox_runtime_label(use_vm_sandbox: bool) -> str:
    return "vm" if use_vm_sandbox else "gvisor"


def modal_sandbox_backend_label() -> str:
    return "v2" if os.environ.get("MODAL_SANDBOX_V2") == "1" else "v1"


def record_network_enforcement(stage: str, runtime: str, layer: str, outcome: str) -> None:
    try:
        client = posthoganalytics.default_client
        if client is None:
            return
        client.metrics.count(
            "tasks.sandbox.network_enforcement",
            1,
            attributes={"stage": stage, "runtime": runtime, "layer": layer, "outcome": outcome},
        )
    except Exception:
        pass


def _runtime_adapter_label(value: str | None) -> str:
    """Bounded label: unexpected values collapse to "other" to cap cardinality."""
    if not value:
        return "unknown"
    return value if value in _ALLOWED_RUNTIME_ADAPTERS else "other"


def resume_mode_label(*, same_run_resume: bool, using_modal_snapshot: bool) -> str:
    if same_run_resume:
        return "same_run_and_snapshot" if using_modal_snapshot else "same_run"
    return "snapshot_only" if using_modal_snapshot else "neither"


def increment_resume_mode(mode: str, *, origin_product: str | None) -> None:
    try:
        _metric_meter({"mode": mode, "origin_product": origin_product or "unknown"}).create_counter(
            "tasks_process_resume_mode",
            "Resuming process-task runs by the resume state available at provision time. "
            "same_run labels identify a restart of the current run. neither means no snapshot "
            "or same-run state accompanied the resume, so the prior working tree could not be restored.",
        ).add(1)
    except Exception:
        pass


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


def record_run_token_usage(
    usage: Mapping[str, Any],
    *,
    origin_product: str | None,
    run_environment: str | None,
    rtk_enabled: bool | None,
    runtime_adapter: str | None,
    status: str | None,
) -> None:
    """Record a terminal run's token expenditure (from ``TaskRun.state.token_usage``).

    Best-effort: a metric failure must never affect the status transition.
    """
    try:
        base_attributes: Attributes = {
            "origin_product": origin_product or "unknown",
            "run_environment": run_environment or "unknown",
            "rtk_enabled": _bool_label(rtk_enabled),
            "runtime_adapter": _runtime_adapter_label(runtime_adapter),
            "status": status or "unknown",
        }
        for kind, key in _RUN_TOKEN_KINDS.items():
            value = usage.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
                _metric_meter({**base_attributes, "kind": kind}).create_counter(
                    "tasks_run_tokens_total",
                    "Token expenditure of terminal task runs, by token kind",
                ).add(int(value))
        total = usage.get("total_tokens")
        if isinstance(total, int | float) and not isinstance(total, bool) and total > 0:
            _metric_meter(base_attributes).create_histogram(
                "tasks_run_total_tokens",
                "Total tokens spent per terminal task run",
            ).record(int(total))
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


def increment_pr_babysit_decision(decision: str) -> None:
    try:
        meter = workflow.metric_meter().with_additional_attributes({"decision": decision})
        meter.create_counter(
            "tasks_pr_babysit_decision",
            "CI follow-up decisions made by the snapshot-driven PR babysit loop",
        ).add(1)
    except Exception:
        pass


def increment_pr_babysit_snapshot(outcome: str, *, pr_state: str = "unknown") -> None:
    try:
        meter = _metric_meter({"outcome": outcome, "pr_state": pr_state})
        meter.create_counter(
            "tasks_pr_babysit_snapshot",
            "PR babysit snapshot fetches for the PR follow-up loop, by outcome",
        ).add(1)
    except Exception:
        pass


def record_sandbox_created(
    runtime: str,
    image_kind: str,
    image_fallback: bool,
    latency_ms: int | None,
    *,
    sandbox_backend: str,
) -> None:
    try:
        meter = _metric_meter(
            {
                "runtime": runtime,
                "image_kind": image_kind,
                "image_fallback": _bool_label(image_fallback),
                "sandbox_backend": sandbox_backend,
            }
        )
        meter.create_counter(
            "tasks_process_sandbox_created",
            "Sandboxes created for process-task runs by runtime and image kind",
        ).add(1)
        if latency_ms is not None:
            meter.create_histogram_timedelta(
                "tasks_process_sandbox_creation_latency",
                "Sandbox creation latency by runtime and image kind",
                unit="ms",
            ).record(dt.timedelta(milliseconds=latency_ms))
    except Exception:
        pass


def record_agent_server_session_init_ms(
    session_init_ms: int,
    boot_path: str | None = None,
    *,
    origin_product: str | None = None,
    runtime: str | None = None,
) -> None:
    try:
        attributes: Attributes = {
            "step": "agent_server_session_init",
            "status": "COMPLETED",
        }
        if boot_path is not None:
            attributes["boot_path"] = boot_path
        if origin_product is not None:
            attributes["origin_product"] = origin_product
        if runtime is not None:
            attributes["runtime"] = runtime
        _metric_meter(attributes).create_histogram_timedelta(
            "tasks_process_sandbox_step_latency",
            "Latency for get_sandbox_for_repository sub-steps",
            unit="ms",
        ).record(dt.timedelta(milliseconds=session_init_ms))
    except Exception:
        pass


def increment_agent_server_readiness_retry(
    attempt: int,
    outcome: str,
    *,
    boot_path: str,
    origin_product: str | None,
    runtime: str,
) -> None:
    try:
        _metric_meter(
            {
                "attempt": attempt,
                "outcome": outcome,
                "boot_path": boot_path,
                "origin_product": origin_product or "unknown",
                "runtime": runtime,
            }
        ).create_counter(
            "tasks_process_agent_server_readiness_retry",
            "Agent-server readiness retries that re-enter the start path",
        ).add(1)
    except Exception:
        pass


def record_boot_total_ms(
    boot_total_ms: int,
    *,
    boot_path: str,
    used_snapshot: bool | None,
    has_repo: bool,
    origin_product: str | None,
    runtime: str,
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
            "runtime": runtime,
        }
        _metric_meter(attributes).create_histogram_timedelta(
            "tasks_boot_total_latency",
            "Wall-clock latency from workflow start to agent-server ready",
            unit="ms",
        ).record(dt.timedelta(milliseconds=boot_total_ms))
    except Exception:
        pass


class StepTimer:
    def __init__(
        self,
        step: str,
        used_snapshot: bool | None = None,
        boot_path: str | None = None,
        *,
        origin_product: str | None = None,
        runtime: str | None = None,
        sandbox_backend: str | None = None,
    ) -> None:
        self.step = step
        self.used_snapshot = used_snapshot
        self.boot_path = boot_path
        self.origin_product = origin_product
        self.runtime = runtime
        self.sandbox_backend = sandbox_backend
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
        if self.origin_product is not None:
            attributes["origin_product"] = self.origin_product
        if self.runtime is not None:
            attributes["runtime"] = self.runtime
        if self.sandbox_backend is not None:
            attributes["sandbox_backend"] = self.sandbox_backend

        try:
            _metric_meter(attributes).create_histogram_timedelta(
                "tasks_process_sandbox_step_latency",
                "Latency for get_sandbox_for_repository sub-steps",
                unit="ms",
            ).record(delta)
        except Exception:
            pass

        self._start_counter = None
