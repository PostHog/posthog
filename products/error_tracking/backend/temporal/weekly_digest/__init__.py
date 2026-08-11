from products.error_tracking.backend.temporal.weekly_digest.activities import (
    cleanup_digest_orgs_activity,
    get_digest_orgs_activity,
    load_page_orgs_activity,
    send_org_digest_activity,
)
from products.error_tracking.backend.temporal.weekly_digest.workflow import (
    ErrorTrackingWeeklyDigestPageWorkflow,
    ErrorTrackingWeeklyDigestWorkflow,
)

WORKFLOWS = [ErrorTrackingWeeklyDigestWorkflow, ErrorTrackingWeeklyDigestPageWorkflow]
ACTIVITIES = [
    get_digest_orgs_activity,
    load_page_orgs_activity,
    send_org_digest_activity,
    cleanup_digest_orgs_activity,
]

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "ErrorTrackingWeeklyDigestPageWorkflow",
    "ErrorTrackingWeeklyDigestWorkflow",
    "cleanup_digest_orgs_activity",
    "get_digest_orgs_activity",
    "load_page_orgs_activity",
    "send_org_digest_activity",
]
