from enum import Enum
from typing import Union

from posthog.rbac.user_access_control import ACCESS_CONTROL_RESOURCES
from posthog.scopes import APIScopeObject


class NotificationType(str, Enum):
    COMMENT_MENTION = "comment_mention"


class Priority(str, Enum):
    NORMAL = "normal"
    CRITICAL = "critical"


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


class NotificationOnlyResourceType(str, Enum):
    """Resource types that only exist in the notification system (no AC counterpart)."""

    PIPELINE = "pipeline"
    APPROVAL = "approval"
    COMMENT = "comment"


# Derived from APIScopeObject (used by ACCESS_CONTROL_RESOURCES) — keep in sync
# if ACCESS_CONTROL_RESOURCES changes its element type
type NotificationResourceType = Union[APIScopeObject, NotificationOnlyResourceType]

AC_RESOURCE_TYPES: set[str] = set(ACCESS_CONTROL_RESOURCES)
