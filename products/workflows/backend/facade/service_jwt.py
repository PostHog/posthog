"""The scoped service JWT purposes that the workflow callback endpoints verify.

The plugin server mints these tokens for the "Create AI task" and "Run scout" workflow steps,
and for the batch resolver that reads recipient list pages.
"""

from products.workflows.backend.service_jwt import (
    TASKS_CREATE_PURPOSE,
    WORKFLOW_RECIPIENT_LIST_PURPOSE,
    WORKFLOW_SCOUT_RUN_PURPOSE,
)

__all__ = ["TASKS_CREATE_PURPOSE", "WORKFLOW_RECIPIENT_LIST_PURPOSE", "WORKFLOW_SCOUT_RUN_PURPOSE"]
