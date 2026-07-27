from products.error_tracking.backend.temporal.lifecycle.issue_created import (
    ACTIVITIES as ISSUE_CREATED_ACTIVITIES,
    WORKFLOWS as ISSUE_CREATED_WORKFLOWS,
    ErrorTrackingIssueCreatedWorkflow,
)

WORKFLOWS = ISSUE_CREATED_WORKFLOWS
ACTIVITIES = ISSUE_CREATED_ACTIVITIES

__all__ = ["ACTIVITIES", "WORKFLOWS", "ErrorTrackingIssueCreatedWorkflow"]
