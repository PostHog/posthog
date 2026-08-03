from products.error_tracking.backend.temporal.weekly_digest.activities import (
    get_digest_orgs_activity,
    send_org_digest_activity,
)
from products.error_tracking.backend.temporal.weekly_digest.workflow import (
    ErrorTrackingWeeklyDigestPageWorkflow,
    ErrorTrackingWeeklyDigestWorkflow,
)

WORKFLOWS = [ErrorTrackingWeeklyDigestWorkflow, ErrorTrackingWeeklyDigestPageWorkflow]
ACTIVITIES = [get_digest_orgs_activity, send_org_digest_activity]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingWeeklyDigestPageWorkflow",
    "ErrorTrackingWeeklyDigestWorkflow",
    "get_digest_orgs_activity",
    "send_org_digest_activity",
]
