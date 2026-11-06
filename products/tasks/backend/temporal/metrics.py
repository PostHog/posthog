import os
import time
import inspect
import datetime as dt
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, ContextDecorator
from functools import wraps
from typing import Any, TypeVar, cast

import posthoganalytics
from opentelemetry import trace
from opentelemetry.trace import Span
from temporalio import activity, workflow
from temporalio.common import MetricMeter

from products.tasks.backend.constants import RESUME_SNAPSHOT_KIND
from products.tasks.backend.logic.services.model_catalogue import runtime_adapter_for

Attributes = dict[str, str | int | float | bool]
tracer = trace.get_tracer(__name__)
F = TypeVar("F", bound=Callable[..., object])

TASKS_LATENCY_HISTOGRAM_METRICS = (
    "tasks_process_sandbox_step_latency",
    "tasks_process_snapshot_create_latency",
    "tasks_boot_total_latency",
    "tasks_agent_boot_milestone_latency",
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

TASKS_SDK_LATENCY_HISTOGRAM_METRICS = (
    "temporal_activity_execution_latency",
    "temporal_activity_schedule_to_start_latency",
    "temporal_workflow_task_execution_latency",
)
TASKS_SDK_LATENCY_HISTOGRAM_BUCKETS = [
    1.0,
    10.0,
    20.0,
    50.0,
    100.0,
    200.0,
    250.0,
    500.0,
    1_000.0,
    2_500.0,
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
    1_000_000.0,
]

TASKS_LAUNCH_PREPARATION_HISTOGRAM_METRICS = ("tasks_modal_launch_preparation_latency",)
TASKS_LAUNCH_PREPARATION_HISTOGRAM_BUCKETS = [
    100.0,
    250.0,
    500.0,
    750.0,
    1_000.0,
    1_500.0,
    2_000.0,
    2_500.0,
    3_000.0,
    4_000.0,
    5_000.0,
    6_000.0,
    8_000.0,
    10_000.0,
    15_000.0,
    20_000.0,
    30_000.0,
    45_000.0,
    60_000.0,
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

TASKS_RUN_TURNS_HISTOGRAM_METRICS = ("tasks_run_turns",)
TASKS_RUN_TURNS_HISTOGRAM_BUCKETS = [
    1.0,
    2.0,
    4.0,
    8.0,
    16.0,
    32.0,
    64.0,
    128.0,
    256.0,
]

TASKS_MEMORY_PEAK_RATIO_HISTOGRAM_METRICS = ("tasks_sandbox_memory_peak_ratio",)
TASKS_MEMORY_PEAK_RATIO_HISTOGRAM_BUCKETS = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95, 1.0]

TASKS_CPU_PRESSURE_RATIO_HISTOGRAM_METRICS = ("tasks_sandbox_cpu_pressure_ratio",)
TASKS_CPU_PRESSURE_RATIO_HISTOGRAM_BUCKETS = TASKS_MEMORY_PEAK_RATIO_HISTOGRAM_BUCKETS

TASKS_NETWORK_BYTES_HISTOGRAM_METRICS = ("tasks_sandbox_network_bytes",)
TASKS_NETWORK_BYTES_HISTOGRAM_BUCKETS = [
    1_048_576.0,
    4_194_304.0,
    16_777_216.0,
    67_108_864.0,
    268_435_456.0,
    1_073_741_824.0,
    4_294_967_296.0,
    17_179_869_184.0,
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


def _model_label(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        return "unknown"
    normalized = value.strip().lower()
    return normalized if runtime_adapter_for(normalized) else "other"


def resume_mode_label(*, same_run_resume: bool, using_modal_snapshot: bool, from_import_run: bool = False) -> str:
    if same_run_resume:
        return "same_run_and_snapshot" if using_modal_snapshot else "same_run"
    if using_modal_snapshot:
        return "snapshot_only"
    # An import run never had a sandbox, so there is no working tree to lose: the successor
    # starts from the transcript alone by design, not because a snapshot went missing.
    return "imported_transcript" if from_import_run else "neither"


def increment_resume_mode(mode: str, *, origin_product: str | None) -> None:
    try:
        _metric_meter({"mode": mode, "origin_product": origin_product or "unknown"}).create_counter(
            "tasks_process_resume_mode",
            "Resuming process-task runs by the resume state available at provision time. "
            "same_run labels identify a restart of the current run. neither means no snapshot "
            "or same-run state accompanied the resume, so the prior working tree could not be restored. "
            "imported_transcript means the resumed run only held an imported transcript and had no tree.",
        ).add(1)
    except Exception:
        pass


def _snapshot_kind_label(snapshot_source: str) -> str:
    if snapshot_source == "resume":
        return RESUME_SNAPSHOT_KIND
    if snapshot_source == "repository":
        return "filesystem"
    return "none"


def increment_snapshot_usage(used_snapshot: bool, *, snapshot_source: str = "unknown") -> None:
    try:
        meter = _metric_meter(
            {
                "used_snapshot": _bool_label(used_snapshot),
                "snapshot_source": snapshot_source,
                "snapshot_kind": _snapshot_kind_label(snapshot_source),
            }
        )
        meter.create_counter(
            "tasks_process_snapshot_usage",
            "Number of process-task runs by final snapshot usage",
        ).add(1)
    except Exception:
        pass


def increment_snapshot_restore(snapshot_source: str, outcome: str) -> None:
    try:
        meter = _metric_meter(
            {
                "snapshot_source": snapshot_source,
                "snapshot_kind": _snapshot_kind_label(snapshot_source),
                "outcome": outcome,
            }
        )
        meter.create_counter(
            "tasks_process_snapshot_restore",
            "Snapshot restore outcomes for process-task sandbox creation",
        ).add(1)
    except Exception:
        pass


def increment_snapshot_create(outcome: str) -> None:
    try:
        meter = _metric_meter({"snapshot_kind": RESUME_SNAPSHOT_KIND, "outcome": outcome})
        meter.create_counter(
            "tasks_process_snapshot_create",
            "Resume snapshot creation outcomes for process-task runs",
        ).add(1)
    except Exception:
        pass


def record_snapshot_create_latency_ms(outcome: str, latency_ms: int) -> None:
    try:
        delta = dt.timedelta(milliseconds=latency_ms)
        _metric_meter({"snapshot_kind": RESUME_SNAPSHOT_KIND, "outcome": outcome}).create_histogram_timedelta(
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
    benjamin_enabled: bool | None,
    model: str | None,
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
            "benjamin_enabled": _bool_label(benjamin_enabled),
            "model": _model_label(model),
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
        meter = _metric_meter(base_attributes)
        for name, description, key in (
            ("tasks_run_total_tokens", "Total tokens spent per terminal task run", "total_tokens"),
            ("tasks_run_turns", "Agent turns per terminal task run", "turns"),
        ):
            value = usage.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool) and value > 0:
                meter.create_histogram(name, description).record(int(value))
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


def increment_sandbox_wedge_probe(verdict: str, write_stage: str) -> None:
    try:
        meter = _metric_meter({"verdict": verdict, "write_stage": write_stage})
        meter.create_counter(
            "tasks_sandbox_wedge_probe",
            "Sandbox pressure probe results after credential file write failures",
        ).add(1)
    except Exception:
        pass


def increment_memory_watchdog_events(event: str, count: int) -> None:
    if count <= 0:
        return
    try:
        _metric_meter({"event": event}).create_counter(
            "tasks_sandbox_memory_watchdog_events",
            "Sandbox memory watchdog events read at teardown",
        ).add(count)
    except Exception:
        pass


def increment_memory_watchdog_teardown(status: str) -> None:
    try:
        _metric_meter({"status": status}).create_counter(
            "tasks_sandbox_memory_watchdog_teardown",
            "Sandbox memory watchdog heartbeat status at teardown",
        ).add(1)
    except Exception:
        pass


def record_memory_peak_ratio(ratio: float) -> None:
    try:
        _metric_meter().create_histogram_float(
            "tasks_sandbox_memory_peak_ratio",
            "Peak sandbox memory use as a fraction of the limit, read at teardown",
        ).record(ratio)
    except Exception:
        pass


def increment_sandbox_exit_status(status: str, runtime: str) -> None:
    try:
        _metric_meter({"status": status, "runtime": runtime}).create_counter(
            "tasks_sandbox_exit_status",
            "Sandbox exit status read at cleanup, running when the sandbox was still alive, unknown when the poll failed",
        ).add(1)
    except Exception:
        pass


def record_sandbox_network_bytes(direction: str, value: int) -> None:
    try:
        _metric_meter({"direction": direction}).create_histogram(
            "tasks_sandbox_network_bytes",
            "Sandbox network bytes over non-loopback interfaces, read at teardown",
        ).record(value)
    except Exception:
        pass


def record_sandbox_cpu_pressure_ratio(ratio: float) -> None:
    try:
        _metric_meter().create_histogram_float(
            "tasks_sandbox_cpu_pressure_ratio",
            "Fraction of sandbox uptime with some task stalled on CPU, read at teardown",
        ).record(ratio)
    except Exception:
        pass


def increment_tool_call_only_heartbeat() -> None:
    try:
        _metric_meter().create_counter(
            "tasks_tool_call_only_heartbeat",
            "Run keep-alives carried only by an unfinished tool call through a long event silence",
        ).add(1)
    except Exception:
        pass


def increment_sandbox_process_killed_notification() -> None:
    try:
        _metric_meter().create_counter(
            "tasks_sandbox_process_killed_notifications",
            "Sandbox memory watchdog kills relayed from the agent server to the run",
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


def record_startup_step_event(
    step: str,
    duration_ms: int,
    attributes: Attributes,
    *,
    started_at: dt.datetime | None = None,
) -> None:
    try:
        context = posthoganalytics.get_tags()
        run_id = context.get("run_id")
        if not isinstance(run_id, str) or not run_id:
            return
        properties: dict[str, object] = {
            "$process_person_profile": False,
            **{
                key: context[key]
                for key in (
                    "run_id",
                    "task_id",
                    "origin_product",
                    "run_environment",
                    "mode",
                    "run_source",
                    "runtime_adapter",
                    "provider",
                )
                if key in context
            },
            **attributes,
            "step": step,
            "duration_ms": duration_ms,
        }
        if started_at is not None:
            properties["started_at"] = started_at.isoformat()
            properties["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
        if activity.in_activity():
            info = activity.info()
            properties.update(
                {
                    "temporal_activity_id": info.activity_id,
                    "temporal_activity_type": info.activity_type,
                    "temporal_attempt": info.attempt,
                    "temporal_workflow_id": info.workflow_id,
                    "temporal_workflow_run_id": info.workflow_run_id,
                }
            )
        posthoganalytics.capture(
            "task_startup_step_completed",
            distinct_id=run_id,
            properties=properties,
            send_feature_flags=False,
        )
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
            "Latency for sandbox provisioning sub-steps",
            unit="ms",
        ).record(dt.timedelta(milliseconds=session_init_ms))
    except Exception:
        pass
    record_startup_step_event("agent_server_session_init", session_init_ms, attributes)


def record_agent_server_step_ms(
    step: str,
    duration_ms: int,
    boot_path: str,
    *,
    status: str = "COMPLETED",
    used_snapshot: bool | None = None,
    origin_product: str | None = None,
    runtime: str | None = None,
) -> None:
    try:
        attributes: Attributes = {
            "step": step,
            "used_snapshot": _bool_label(used_snapshot),
            "status": status,
            "boot_path": boot_path,
        }
        if origin_product is not None:
            attributes["origin_product"] = origin_product
        if runtime is not None:
            attributes["runtime"] = runtime
        _metric_meter(attributes).create_histogram_timedelta(
            "tasks_process_sandbox_step_latency",
            "Latency for sandbox provisioning sub-steps",
            unit="ms",
        ).record(dt.timedelta(milliseconds=duration_ms))
    except Exception:
        pass
    record_startup_step_event(step, duration_ms, attributes)


def record_agent_server_boot_phases_ms(
    boot_phases_ms: Mapping[str, int],
    boot_path: str,
    *,
    used_snapshot: bool | None = None,
    origin_product: str | None = None,
    runtime: str | None = None,
) -> None:
    for phase, duration_ms in boot_phases_ms.items():
        record_agent_server_step_ms(
            f"agent_server_phase_{phase}",
            duration_ms,
            boot_path,
            used_snapshot=used_snapshot,
            origin_product=origin_product,
            runtime=runtime,
        )


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


def record_agent_boot_milestone_ms(
    since_agent_ready_ms: int,
    *,
    milestone: str,
    origin_product: str | None,
    boot_path: str | None,
    runtime: str,
    sandbox_backend: str | None,
    runtime_adapter: str | None,
    prewarmed: bool,
) -> None:
    """Prometheus twin of the boot milestone analytics events, plotted next to `tasks_boot_total_latency`."""
    try:
        attributes: Attributes = {
            "milestone": milestone,
            "origin_product": origin_product or "unknown",
            "boot_path": boot_path or "unknown",
            "runtime": runtime,
            "sandbox_backend": sandbox_backend or "unknown",
            "runtime_adapter": _runtime_adapter_label(runtime_adapter),
            "prewarmed": _bool_label(prewarmed),
        }
        workflow.metric_meter().with_additional_attributes(attributes).create_histogram_timedelta(
            "tasks_agent_boot_milestone_latency",
            "Latency from agent-server ready to the first agent boot milestone",
            unit="ms",
        ).record(dt.timedelta(milliseconds=since_agent_ready_ms))
    except Exception:
        pass


class StepTimer(ContextDecorator):
    def __call__(self, func: F) -> F:
        if not inspect.iscoroutinefunction(func):
            return super().__call__(func)

        @wraps(func)
        async def timed(*args: object, **kwargs: object) -> object:
            with self._recreate_cm():
                return await func(*args, **kwargs)

        return cast(F, timed)

    def __init__(
        self,
        step: str,
        used_snapshot: bool | None = None,
        boot_path: str | None = None,
        *,
        origin_product: str | None = None,
        runtime: str | None = None,
        sandbox_backend: str | None = None,
        status_tag: str | None = None,
    ) -> None:
        self.step = step
        self.used_snapshot = used_snapshot
        self.boot_path = boot_path
        self.origin_product = origin_product
        self.runtime = runtime
        self.sandbox_backend = sandbox_backend
        self.status_tag = status_tag
        # Elapsed wall-clock of the step, readable after the context exits so callers
        # can thread the same number into activity outputs / analytics events.
        self.elapsed_ms: int | None = None
        self._start_counter: float | None = None
        self._started_at: dt.datetime | None = None
        self._span: AbstractContextManager[Span] | None = None

    def _recreate_cm(self) -> "StepTimer":
        return StepTimer(
            self.step,
            used_snapshot=self.used_snapshot,
            boot_path=self.boot_path,
            origin_product=self.origin_product,
            runtime=self.runtime,
            sandbox_backend=self.sandbox_backend,
            status_tag=self.status_tag,
        )

    def set_used_snapshot(self, used_snapshot: bool) -> None:
        self.used_snapshot = used_snapshot

    def __enter__(self) -> "StepTimer":
        self._span = tracer.start_as_current_span("tasks.step." + self.step)
        self._span.__enter__()
        self._started_at = dt.datetime.now(dt.UTC)
        self._start_counter = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if self._start_counter is None:
            raise RuntimeError("StepTimer used without calling __enter__")

        delta_ms = int((time.perf_counter() - self._start_counter) * 1000)
        self.elapsed_ms = delta_ms
        if self._span is not None:
            self._span.__exit__(exc_type, exc_value, traceback)
            self._span = None
        delta = dt.timedelta(milliseconds=delta_ms)

        context = posthoganalytics.get_tags()
        used_snapshot = self.used_snapshot if self.used_snapshot is not None else context.get("used_snapshot")
        attributes: Attributes = {
            "step": self.step,
            "used_snapshot": _bool_label(used_snapshot if isinstance(used_snapshot, bool) else None),
            "status": "FAILED" if exc_value is not None else "COMPLETED",
        }
        if self.status_tag is not None and exc_value is None:
            attributes["status"] = str(context.get(self.status_tag, "FAILED"))
        for key, explicit in (
            ("boot_path", self.boot_path),
            ("origin_product", self.origin_product),
            ("runtime", self.runtime),
            ("sandbox_backend", self.sandbox_backend),
        ):
            value = explicit if explicit is not None else context.get(key)
            if isinstance(value, str):
                attributes[key] = value

        try:
            _metric_meter(attributes).create_histogram_timedelta(
                "tasks_process_sandbox_step_latency",
                "Latency for sandbox provisioning sub-steps",
                unit="ms",
            ).record(delta)
        except Exception:
            pass

        record_startup_step_event(self.step, delta_ms, attributes, started_at=self._started_at)
        self._start_counter = None
