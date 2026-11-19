"""The scoped service JWT purposes that the workflow callback endpoints verify.

The plugin server mints tokens for the "Create AI task", "Run scout", "Classify with AI",
"Replay Vision", "Add to static cohort" and "Opt out of messages" workflow steps.
"""

from products.workflows.backend.service_jwt import (
    TASKS_CREATE_PURPOSE,
    WORKFLOW_ADD_TO_STATIC_COHORT_PURPOSE,
    WORKFLOW_CLASSIFY_PURPOSE,
    WORKFLOW_MESSAGE_OPT_OUT_PURPOSE,
    WORKFLOW_SCOUT_RUN_PURPOSE,
    WORKFLOW_VISION_REQUEST_PURPOSE,
)

__all__ = [
    "TASKS_CREATE_PURPOSE",
    "WORKFLOW_ADD_TO_STATIC_COHORT_PURPOSE",
    "WORKFLOW_CLASSIFY_PURPOSE",
    "WORKFLOW_MESSAGE_OPT_OUT_PURPOSE",
    "WORKFLOW_SCOUT_RUN_PURPOSE",
    "WORKFLOW_VISION_REQUEST_PURPOSE",
]
