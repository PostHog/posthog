"""Billing-facing exports for the tasks product.

The usage reporter (posthog/tasks/usage_report.py) lives in the ``posthog`` module,
which may only import ``products.tasks`` through the facade (see tach.toml).
"""

from products.tasks.backend.facade.contracts import TaskRunSpend
from products.tasks.backend.logic.services.sandbox_pricing import ComputeRateCardConfigurationError
from products.tasks.backend.logic.services.sandbox_usage import (
    SandboxComputeUsageByTeam,
    SandboxUsageByTeam,
    get_billable_sandbox_compute_usage_by_team,
    get_task_sandbox_usage_by_team,
)
from products.tasks.backend.logic.services.task_usage import (
    TASK_USAGE_SIGNATURE_HEADER,
    TASK_USAGE_TIMESTAMP_HEADER,
    TaskTokenUsageUnavailable,
    TaskUsage,
    get_local_task_run_token_costs,
    get_local_task_token_cost,
    get_task_usage,
)


def get_task_spend(team_id: int, task_id: str) -> TaskRunSpend:
    from products.tasks.backend.models import TaskRun  # noqa: PLC0415 - avoids a models/facade import cycle

    token_cost = compute_cost = 0
    for run in TaskRun.objects.filter(team_id=team_id, task_id=task_id):
        spend = run.get_current_spend()
        token_cost += spend.token_cost
        compute_cost += spend.compute_cost
    return TaskRunSpend(token_cost=token_cost, compute_cost=compute_cost)


__all__ = [
    "TaskRunSpend",
    "get_task_spend",
    "ComputeRateCardConfigurationError",
    "SandboxComputeUsageByTeam",
    "SandboxUsageByTeam",
    "TaskUsage",
    "TaskTokenUsageUnavailable",
    "TASK_USAGE_SIGNATURE_HEADER",
    "TASK_USAGE_TIMESTAMP_HEADER",
    "get_billable_sandbox_compute_usage_by_team",
    "get_local_task_run_token_costs",
    "get_local_task_token_cost",
    "get_task_sandbox_usage_by_team",
    "get_task_usage",
]
