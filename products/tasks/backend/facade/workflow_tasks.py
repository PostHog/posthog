"""Facade for tasks created by a workflow's "Create AI task" action.

The workflows product resolves which workflow is calling and who owns it, then creates
and starts the task through this boundary.
"""

from products.tasks.backend.facade.contracts import WorkflowTaskRateLimits, WorkflowTaskSlackContext
from products.tasks.backend.logic.services.workflow_task_skills import (
    MAX_ATTACHED_SKILLS,
    WorkflowTaskSkillsInvalid,
    validate_skill_names,
)
from products.tasks.backend.logic.services.workflow_tasks import (
    WorkflowTaskConnectorsInvalid,
    WorkflowTaskLimitExceeded,
    WorkflowTaskOriginKeyConflict,
    WorkflowTaskOwnerIneligible,
    WorkflowTaskRateCapped,
    WorkflowTaskTeamRateCapped,
    WorkflowTaskUsageLimited,
    create_workflow_task,
    resolve_connectors,
)

__all__ = [
    "MAX_ATTACHED_SKILLS",
    "WorkflowTaskConnectorsInvalid",
    "WorkflowTaskLimitExceeded",
    "WorkflowTaskOriginKeyConflict",
    "WorkflowTaskOwnerIneligible",
    "WorkflowTaskRateCapped",
    "WorkflowTaskRateLimits",
    "WorkflowTaskSkillsInvalid",
    "WorkflowTaskSlackContext",
    "WorkflowTaskTeamRateCapped",
    "WorkflowTaskUsageLimited",
    "create_workflow_task",
    "resolve_connectors",
    "validate_skill_names",
]
