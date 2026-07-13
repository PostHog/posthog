from enum import Enum
from typing import Union

from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES
from posthog.scopes import APIScopeObject


class NotificationType(str, Enum):
    COMMENT_MENTION = "comment_mention"
    ALERT_FIRING = "alert_firing"
    ISSUE_ASSIGNED = "issue_assigned"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    EXPERIMENT_CONCLUDED = "experiment_concluded"
    PIPELINE_FAILURE = "pipeline_failure"
    PROJECT_CREATED = "project_created"
    USAGE_SPIKE = "usage_spike"
    REMINDER = "reminder"
    WEB_ANALYTICS_DIGEST = "web_analytics_digest"
    ACHIEVEMENT_UNLOCKED = "achievement_unlocked"


class Priority(str, Enum):
    NORMAL = "normal"
    CRITICAL = "critical"


# Discriminator for transient "resource edited elsewhere" realtime events. These ride the
# notifications SSE transport but are NOT inbox notifications (no NotificationEvent row, no unread
# count) — see products.notifications.backend.logic.publish_resource_edited.
RESOURCE_EDITED_EVENT_TYPE = "resource_edited"


class TargetType(str, Enum):
    USER = "user"
    TEAM = "team"
    ORGANIZATION = "organization"
    ROLE = "role"


class SourceType(str, Enum):
    REPLAY = "replay"
    NOTEBOOK = "notebook"
    INSIGHT = "insight"
    FEATURE_FLAG = "feature_flag"
    DASHBOARD = "dashboard"
    SURVEY = "survey"
    EXPERIMENT = "experiment"
    ERROR_TRACKING = "error_tracking"
    CUSTOMER_ANALYTICS = "customer_analytics"


class NotificationOnlyResourceType(str, Enum):
    """Resource types that only exist in the notification system (no AC counterpart)."""

    PIPELINE = "pipeline"
    APPROVAL = "approval"
    COMMENT = "comment"


# Derived from APIScopeObject (used by ACCESS_CONTROL_RESOURCES) — keep in sync
# if ACCESS_CONTROL_RESOURCES changes its element type
type NotificationResourceType = Union[APIScopeObject, NotificationOnlyResourceType]

AC_RESOURCE_TYPES: set[str] = set(ACCESS_CONTROL_RESOURCES)
