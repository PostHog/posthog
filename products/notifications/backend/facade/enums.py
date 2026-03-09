from enum import Enum


class NotificationType(str, Enum):
    COMMENT_MENTION = "comment_mention"
    ALERT_FIRING = "alert_firing"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    PIPELINE_FAILURE = "pipeline_failure"
    ISSUE_ASSIGNED = "issue_assigned"


class Priority(str, Enum):
    NORMAL = "normal"
    URGENT = "urgent"
