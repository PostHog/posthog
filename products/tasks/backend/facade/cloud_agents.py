"""Facade for the tasks behind the Cloud Agents public API.

The Cloud Agents product authorizes its own callers, then creates, resumes and reads its
tasks through this boundary. Every function here is scoped to the reserved ``cloud_agents``
origin and to the team.

The run-scoped functions of the general facade also work for these tasks:
``signal_task_run_user_message``, ``read_task_run_history`` and ``get_task_run_detail`` in
``facade/api.py``, and ``cancel_task_run`` in ``facade/cancellation.py``. They look a run up by
run id, task id and team id and do no visibility check, so an internal task is not hidden from
them. They also do no origin check: resolve the run with ``get_cloud_agent_task_run`` first.
"""

from products.tasks.backend.facade.contracts import (
    CloudAgentActiveRunDTO,
    CloudAgentPullRequestDTO,
    CloudAgentSessionDTO,
    CloudAgentTaskDTO,
    CloudAgentTaskStateDTO,
    CloudAgentTaskUsageDTO,
    CloudAgentUsageDTO,
)
from products.tasks.backend.logic.services.cloud_agent_tasks import (
    OUTPUT_SCHEMA_MAX_BYTES,
    CloudAgentRunNotResumable,
    CloudAgentTaskError,
    CloudAgentTaskInvalid,
    CloudAgentTaskNotFound,
    CloudAgentTaskOriginKeyConflict,
    TaskRunEnd,
    classify_task_run_end,
    count_active_cloud_agent_runs,
    create_cloud_agent_task,
    get_cloud_agent_task_run,
    get_cloud_agent_task_states,
    get_cloud_agent_tasks_billing,
    list_active_billable_cloud_agent_runs,
    list_cloud_agent_task_ids,
    list_cloud_agent_task_run_ids,
    resume_cloud_agent_task,
    summarize_cloud_agent_usage,
    validate_cloud_agent_output_schema,
)
from products.tasks.backend.temporal.constants import MAX_INACTIVITY_TIMEOUT_SECONDS

__all__ = [
    "MAX_INACTIVITY_TIMEOUT_SECONDS",
    "OUTPUT_SCHEMA_MAX_BYTES",
    "CloudAgentActiveRunDTO",
    "CloudAgentPullRequestDTO",
    "CloudAgentRunNotResumable",
    "CloudAgentSessionDTO",
    "CloudAgentTaskDTO",
    "CloudAgentTaskError",
    "CloudAgentTaskInvalid",
    "CloudAgentTaskNotFound",
    "CloudAgentTaskOriginKeyConflict",
    "CloudAgentTaskStateDTO",
    "CloudAgentTaskUsageDTO",
    "CloudAgentUsageDTO",
    "TaskRunEnd",
    "classify_task_run_end",
    "count_active_cloud_agent_runs",
    "create_cloud_agent_task",
    "get_cloud_agent_task_run",
    "get_cloud_agent_task_states",
    "get_cloud_agent_tasks_billing",
    "list_active_billable_cloud_agent_runs",
    "list_cloud_agent_task_ids",
    "list_cloud_agent_task_run_ids",
    "resume_cloud_agent_task",
    "summarize_cloud_agent_usage",
    "validate_cloud_agent_output_schema",
]
