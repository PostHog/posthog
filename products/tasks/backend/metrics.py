from typing import TYPE_CHECKING, Literal

from prometheus_client import Counter

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


TaskWorkflowStartOutcome = Literal["attempted", "blocked", "failed", "started"]
_ALLOWED_MODES = {"background", "interactive"}
_ALLOWED_RUN_SOURCES = {"manual", "signal_report"}
_ALLOWED_RUNTIME_ADAPTERS = {"claude", "codex"}


TASK_RUN_CREATED_TOTAL = Counter(
    "posthog_tasks_task_run_created_total",
    "TaskRun rows created by the Tasks product",
    labelnames=["origin_product", "run_environment", "mode", "run_source", "runtime_adapter"],
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
        "outcome",
        "reason",
    ],
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
        }

    state = task_run.state if isinstance(task_run.state, dict) else {}
    return {
        "origin_product": _metric_label(getattr(task_run.task, "origin_product", None)),
        "run_environment": _metric_label(task_run.environment),
        "mode": _bounded_metric_label(state.get("mode"), _ALLOWED_MODES),
        "run_source": _bounded_metric_label(state.get("run_source"), _ALLOWED_RUN_SOURCES),
        "runtime_adapter": _bounded_metric_label(state.get("runtime_adapter"), _ALLOWED_RUNTIME_ADAPTERS),
    }


def observe_task_run_created(task_run: "TaskRun") -> None:
    TASK_RUN_CREATED_TOTAL.labels(**_task_run_labels(task_run)).inc()


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
