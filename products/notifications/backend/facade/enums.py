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


class TargetType(str, Enum):
    USER = "user"
    TEAM = "team"
    ORGANIZATION = "organization"
    ROLE = "role"


class NotificationResourceType(str, Enum):
    DASHBOARD = "dashboard"
    EXPERIMENT = "experiment"
    FEATURE_FLAG = "feature_flag"
    INSIGHT = "insight"
    NOTEBOOK = "notebook"
    SESSION_RECORDING = "session_recording"
    SURVEY = "survey"
    ERROR_TRACKING = "error_tracking"
    LOGS = "logs"
    PIPELINE = "pipeline"
    ALERT = "alert"
    APPROVAL = "approval"
    COMMENT = "comment"


AC_RESOURCE_TYPES = {
    NotificationResourceType.DASHBOARD,
    NotificationResourceType.EXPERIMENT,
    NotificationResourceType.FEATURE_FLAG,
    NotificationResourceType.INSIGHT,
    NotificationResourceType.NOTEBOOK,
    NotificationResourceType.SESSION_RECORDING,
    NotificationResourceType.SURVEY,
    NotificationResourceType.ERROR_TRACKING,
    NotificationResourceType.LOGS,
}
