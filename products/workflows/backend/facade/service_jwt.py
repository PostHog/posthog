"""The scoped service JWT purposes that the workflow callback endpoints verify.

The plugin server mints these tokens for the "Create AI task", "Run scout" and "Analyze sessions with Replay vision" workflow steps.
"""

from products.workflows.backend.service_jwt import (
    TASKS_CREATE_PURPOSE,
    WORKFLOW_SCOUT_RUN_PURPOSE,
    WORKFLOW_VISION_REQUEST_PURPOSE,
)

__all__ = ["TASKS_CREATE_PURPOSE", "WORKFLOW_SCOUT_RUN_PURPOSE", "WORKFLOW_VISION_REQUEST_PURPOSE"]
