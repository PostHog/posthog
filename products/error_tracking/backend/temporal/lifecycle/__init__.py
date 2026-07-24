from products.error_tracking.backend.temporal.lifecycle.issue_created import (
    ACTIVITIES as ISSUE_CREATED_ACTIVITIES,
    WORKFLOWS as ISSUE_CREATED_WORKFLOWS,
    ErrorTrackingIssueCreatedWorkflow,
)
from products.error_tracking.backend.temporal.lifecycle.issue_reopened import (
    ACTIVITIES as ISSUE_REOPENED_ACTIVITIES,
    WORKFLOWS as ISSUE_REOPENED_WORKFLOWS,
    ErrorTrackingIssueReopenedWorkflow,
)

WORKFLOWS = ISSUE_CREATED_WORKFLOWS + ISSUE_REOPENED_WORKFLOWS
ACTIVITIES = ISSUE_CREATED_ACTIVITIES + ISSUE_REOPENED_ACTIVITIES

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingIssueCreatedWorkflow",
    "ErrorTrackingIssueReopenedWorkflow",
]
