from typing import TYPE_CHECKING, Literal

import structlog
from prometheus_client import Counter, Histogram

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


TaskWorkflowStartOutcome = Literal["attempted", "blocked", "failed", "started"]
# Outcome of an SSE task-run stream connection when it closes.
#   completed         — stream reached its completion sentinel
#   stream_error      — Redis/stream error sentinel ended the connection
#   unavailable       — stream key never appeared within the wait timeout
#   client_disconnect — client went away (GeneratorExit) before completion
#   rotated           — per-connection cap reached; clean EOF, client resumes
StreamConnectionOutcome = Literal["completed", "stream_error", "unavailable", "client_disconnect", "rotated"]
_ALLOWED_MODES = {"background", "interactive"}
_ALLOWED_RUN_SOURCES = {"manual", "signal_report"}
_ALLOWED_RUNTIME_ADAPTERS = {"claude", "codex"}


TASK_RUN_CREATED_TOTAL = Counter(
    "posthog_tasks_task_run_created_total",
    "TaskRun rows created by the Tasks product",
    labelnames=["origin_product", "run_environment", "mode", "run_source", "runtime_adapter", "prewarmed"],
)

TASK_RUN_WORKFLOW_START_TOTAL = Counter(
    "posthog_tasks_task_run_workflow_start_total",
    "TaskRun workflow start lifecycle events",
    labelnames=[
        "origin_product",
        "run_environment",
        "mode",
        "run_source",
        "runtime_adapter",
        "prewarmed",
        "outcome",
        "reason",
    ],
)

TASK_RUN_DISPATCH_CALLBACK_TOTAL = Counter(
    "posthog_tasks_task_run_dispatch_callback_total",
    "on_commit workflow-dispatch callback lifecycle: 'scheduled' when registered, 'fired' when it runs. "
    "scheduled minus fired is the count of lost callbacks that strand a run in QUEUED.",
    labelnames=[
        "origin_product",
        "run_environment",
        "mode",
        "run_source",
        "runtime_adapter",
        "prewarmed",
        "phase",
    ],
)

PREWARMED_ACTIVATED_TOTAL = Counter(
    "posthog_tasks_prewarmed_activated_total",
    "Pre-warmed Runs that received their first user message (the warm sandbox got used, not reaped)",
    labelnames=["origin_product"],
)

TASK_RUN_FAILED_TOTAL = Counter(
    "posthog_tasks_task_run_failed_total",
    "TaskRun workflow failures with bounded attribution labels",
    labelnames=[
        "origin_product",
        "mode",
        "run_source",
        "runtime_adapter",
        "error_type",
        "temporal_activity_type",
        "temporal_activity_retry_state",
        "cause_error_type",
    ],
)


# Connection lifetimes range from a few seconds (cold reconnect) to the
# per-connection cap. The 120s bucket isolates connections cut at the
# Envoy/Contour response_timeout boundary from genuinely long-lived ones.
STREAM_CONNECTION_DURATION_BUCKETS = [
    1.0,
    5.0,
    15.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    960.0,
    1_800.0,
    3_600.0,
    7_200.0,
    21_600.0,
]
# Stream length is capped at TASK_RUN_STREAM_MAX_LENGTH (~20k); the top buckets
# show how close real runs get to the trim threshold.
STREAM_LENGTH_BUCKETS = [10.0, 50.0, 100.0, 500.0, 1_000.0, 2_500.0, 5_000.0, 10_000.0, 15_000.0, 20_000.0]


TASK_RUN_STREAM_CONNECTIONS_OPENED_TOTAL = Counter(
    "posthog_tasks_task_run_stream_connections_opened_total",
    "SSE task-run stream connections opened",
    labelnames=["origin_product"],
)

TASK_RUN_STREAM_CONNECTIONS_CLOSED_TOTAL = Counter(
    "posthog_tasks_task_run_stream_connections_closed_total",
    "SSE task-run stream connections closed, labeled by how they ended",
    labelnames=["origin_product", "outcome"],
)

TASK_RUN_STREAM_CONNECTION_DURATION_SECONDS = Histogram(
    "posthog_tasks_task_run_stream_connection_duration_seconds",
    "Lifetime of an SSE task-run stream connection",
    labelnames=["origin_product", "outcome"],
    buckets=STREAM_CONNECTION_DURATION_BUCKETS,
)

TASK_RUN_STREAM_LENGTH_ON_CONNECT = Histogram(
    "posthog_tasks_task_run_stream_length_on_connect",
    "Redis stream length observed when an SSE connection reconnects with a cursor",
    buckets=STREAM_LENGTH_BUCKETS,
)

TASK_RUN_STREAM_RESUME_GAP_TOTAL = Counter(
    "posthog_tasks_task_run_stream_resume_gap_total",
    "SSE reconnects whose Last-Event-ID was already trimmed from Redis (events lost for that client)",
    labelnames=["origin_product"],
)

TASK_RUN_AGENT_FAILURE_TOTAL = Counter(
    "posthog_tasks_agent_turn_failed_total",
    "TaskRun transitions to FAILED via the API facade (agent-server turn failures)",
    labelnames=["origin_product", "mode", "run_source", "runtime_adapter"],
)

TASK_RUN_FOLLOWUP_DELIVERY_FAILED_TOTAL = Counter(
    "posthog_tasks_followup_delivery_failed_total",
    "Follow-up user message deliveries to a live sandbox that failed",
    labelnames=["origin_product", "retryable"],
)

TASK_RUN_WIZARD_UNBOUND_TOTAL = Counter(
    "posthog_tasks_wizard_run_unbound_total",
    "Wizard cloud runs that reached a terminal status without an output.pr_url binding",
    labelnames=["status"],
)

PUSH_DISPATCHER_FAILURES_TOTAL = Counter(
    "posthog_tasks_push_dispatcher_failures_total",
    "Push-notification dispatch attempts that failed and were swallowed by the best-effort dispatcher",
    labelnames=["kind", "reason"],
)


def _metric_label(value: object | None) -> str:
    if value is None:
        return "unknown"
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _bounded_metric_label(value: object | None, allowed_values: set[str]) -> str:
    label = _metric_label(value)
    if label == "unknown" or label in allowed_values:
        return label
    return "other"


def _failure_metric_label(value: object | None) -> str:
    label = _metric_label(value)
    if label == "unknown":
        return label
    return label[:100]


def _task_run_labels(task_run: "TaskRun | None") -> dict[str, str]:
    if task_run is None:
        return {
            "origin_product": "unknown",
            "run_environment": "unknown",
            "mode": "unknown",
            "run_source": "unknown",
            "runtime_adapter": "unknown",
            "prewarmed": "unknown",
        }

    state = task_run.state if isinstance(task_run.state, dict) else {}
    return {
        "origin_product": origin_product_label(task_run),
        "run_environment": _metric_label(task_run.environment),
        "mode": _bounded_metric_label(state.get("mode"), _ALLOWED_MODES),
        "run_source": _bounded_metric_label(state.get("run_source"), _ALLOWED_RUN_SOURCES),
        "runtime_adapter": _bounded_metric_label(state.get("runtime_adapter"), _ALLOWED_RUNTIME_ADAPTERS),
        "prewarmed": "true" if state.get("prewarmed") else "false",
    }


def observe_task_run_created(task_run: "TaskRun") -> None:
    TASK_RUN_CREATED_TOTAL.labels(**_task_run_labels(task_run)).inc()


def observe_task_run_dispatch_callback(task_run: "TaskRun | None", *, phase: Literal["scheduled", "fired"]) -> None:
    TASK_RUN_DISPATCH_CALLBACK_TOTAL.labels(**_task_run_labels(task_run), phase=phase).inc()


def observe_task_run_workflow_start(
    task_run: "TaskRun | None",
    *,
    outcome: TaskWorkflowStartOutcome,
    reason: str,
) -> None:
    TASK_RUN_WORKFLOW_START_TOTAL.labels(
        **_task_run_labels(task_run),
        outcome=outcome,
        reason=reason,
    ).inc()


def observe_prewarmed_activated(task_run: "TaskRun") -> None:
    PREWARMED_ACTIVATED_TOTAL.labels(origin_product=origin_product_label(task_run)).inc()


def origin_product_label(task_run: "TaskRun | None") -> str:
    """Bounded origin_product metric label resolved from the task run's task."""
    if task_run is None:
        return "unknown"
    return _metric_label(getattr(task_run.task, "origin_product", None))


def observe_stream_connection_opened(origin_product: str) -> None:
    TASK_RUN_STREAM_CONNECTIONS_OPENED_TOTAL.labels(origin_product=origin_product).inc()


def observe_stream_connection_closed(
    origin_product: str, outcome: StreamConnectionOutcome, duration_seconds: float
) -> None:
    TASK_RUN_STREAM_CONNECTIONS_CLOSED_TOTAL.labels(origin_product=origin_product, outcome=outcome).inc()
    TASK_RUN_STREAM_CONNECTION_DURATION_SECONDS.labels(origin_product=origin_product, outcome=outcome).observe(
        duration_seconds
    )


def observe_stream_length_on_connect(length: int) -> None:
    TASK_RUN_STREAM_LENGTH_ON_CONNECT.observe(length)


def observe_stream_resume_gap(origin_product: str) -> None:
    TASK_RUN_STREAM_RESUME_GAP_TOTAL.labels(origin_product=origin_product).inc()


def observe_task_run_failed(properties: dict[str, object]) -> None:
    TASK_RUN_FAILED_TOTAL.labels(
        origin_product=_metric_label(properties.get("origin_product")),
        mode=_bounded_metric_label(properties.get("mode"), _ALLOWED_MODES),
        run_source=_bounded_metric_label(properties.get("run_source"), _ALLOWED_RUN_SOURCES),
        runtime_adapter=_bounded_metric_label(properties.get("runtime_adapter"), _ALLOWED_RUNTIME_ADAPTERS),
        error_type=_failure_metric_label(properties.get("error_type")),
        temporal_activity_type=_failure_metric_label(properties.get("temporal_activity_type")),
        temporal_activity_retry_state=_failure_metric_label(properties.get("temporal_activity_retry_state")),
        cause_error_type=_failure_metric_label(properties.get("cause_error_type")),
    ).inc()


def observe_agent_turn_failed(task_run: "TaskRun") -> None:
    labels = _task_run_labels(task_run)
    TASK_RUN_AGENT_FAILURE_TOTAL.labels(
        origin_product=labels["origin_product"],
        mode=labels["mode"],
        run_source=labels["run_source"],
        runtime_adapter=labels["runtime_adapter"],
    ).inc()


def observe_wizard_run_unbound(task_run: "TaskRun") -> None:
    """Record a wizard run ending without its PR ever binding.

    Call on terminal status transitions. Every binding failure mode is silent
    (agent used a different branch, webhook undelivered, write swallowed), so
    this counter is the only signal that the wizard PR pipeline regressed.
    """
    state = task_run.state if isinstance(task_run.state, dict) else {}
    if not state.get("wizard_head_branch"):
        return
    output = task_run.output if isinstance(task_run.output, dict) else {}
    if output.get("pr_url"):
        return
    TASK_RUN_WIZARD_UNBOUND_TOTAL.labels(status=task_run.status).inc()
    logger.warning(
        "wizard_run_terminal_without_pr",
        run_id=str(task_run.id),
        status=task_run.status,
        wizard_head_branch=state.get("wizard_head_branch"),
    )


def observe_followup_delivery_failed(task_run: "TaskRun", *, retryable: bool) -> None:
    TASK_RUN_FOLLOWUP_DELIVERY_FAILED_TOTAL.labels(
        origin_product=origin_product_label(task_run),
        retryable="true" if retryable else "false",
    ).inc()
