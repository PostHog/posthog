"""Facade for tasks created by a workflow's "Create AI task" action.

The workflows product resolves which workflow is calling and who owns it, then creates
and starts the task through this boundary.
"""

from products.tasks.backend.facade.contracts import WorkflowTaskSlackContext
from products.tasks.backend.logic.services.workflow_tasks import (
    WorkflowTaskConnectorsInvalid,
    WorkflowTaskLimitExceeded,
    WorkflowTaskOriginKeyConflict,
    WorkflowTaskOwnerIneligible,
    create_workflow_task,
    validate_connectors,
)

__all__ = [
    "WorkflowTaskConnectorsInvalid",
    "WorkflowTaskLimitExceeded",
    "WorkflowTaskOriginKeyConflict",
    "WorkflowTaskOwnerIneligible",
    "WorkflowTaskSlackContext",
    "create_workflow_task",
    "validate_connectors",
]
