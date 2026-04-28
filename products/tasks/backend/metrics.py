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
