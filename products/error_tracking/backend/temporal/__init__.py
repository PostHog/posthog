from products.error_tracking.backend.temporal.alerts import (
    ACTIVITIES as ALERT_ACTIVITIES,
    WORKFLOWS as ALERT_WORKFLOWS,
    ErrorTrackingAlertDeliveryWorkflow,
)
from products.error_tracking.backend.temporal.lifecycle import (
    ACTIVITIES as _LIFECYCLE_ONLY_ACTIVITIES,
    WORKFLOWS as _LIFECYCLE_ONLY_WORKFLOWS,
    ErrorTrackingIssueCreatedWorkflow,
    ErrorTrackingIssueReopenedWorkflow,
    ErrorTrackingIssueSpikingWorkflow,
)
from products.error_tracking.backend.temporal.recommendations_refresh import (
    ACTIVITIES as RECOMMENDATIONS_REFRESH_ACTIVITIES,
    WORKFLOWS as RECOMMENDATIONS_REFRESH_WORKFLOWS,
    ErrorTrackingRecommendationsRefreshWorkflow,
    get_team_batches_activity,
    refresh_recommendations_batch_activity,
)
from products.error_tracking.backend.temporal.spike_event_cleanup import (
    ACTIVITIES as SPIKE_EVENT_ACTIVITIES,
    WORKFLOWS as SPIKE_EVENT_WORKFLOWS,
    ErrorTrackingSpikeEventCleanupWorkflow,
    cleanup_spike_events_activity,
)
from products.error_tracking.backend.temporal.symbol_set_cleanup import (
    ACTIVITIES as SYMBOL_SET_ACTIVITIES,
    WORKFLOWS as SYMBOL_SET_WORKFLOWS,
    ErrorTrackingSymbolSetCleanupWorkflow,
    cleanup_symbol_sets_activity,
)
from products.error_tracking.backend.temporal.weekly_digest import (
    ACTIVITIES as WEEKLY_DIGEST_ACTIVITIES,
    WORKFLOWS as WEEKLY_DIGEST_WORKFLOWS,
    ErrorTrackingWeeklyDigestWorkflow,
    get_digest_orgs_activity,
    send_org_digest_activity,
)

# Alert delivery runs on the lifecycle task queue: it is started by the lifecycle
# activities and by Django mutations, and the queue's workers are already deployed.
LIFECYCLE_WORKFLOWS = _LIFECYCLE_ONLY_WORKFLOWS + ALERT_WORKFLOWS
LIFECYCLE_ACTIVITIES = _LIFECYCLE_ONLY_ACTIVITIES + ALERT_ACTIVITIES

WORKFLOWS = SYMBOL_SET_WORKFLOWS + SPIKE_EVENT_WORKFLOWS + RECOMMENDATIONS_REFRESH_WORKFLOWS + WEEKLY_DIGEST_WORKFLOWS
ACTIVITIES = (
    SYMBOL_SET_ACTIVITIES + SPIKE_EVENT_ACTIVITIES + RECOMMENDATIONS_REFRESH_ACTIVITIES + WEEKLY_DIGEST_ACTIVITIES
)

__all__ = [
    "ACTIVITIES",
    "LIFECYCLE_ACTIVITIES",
    "LIFECYCLE_WORKFLOWS",
    "WORKFLOWS",
    "ErrorTrackingAlertDeliveryWorkflow",
    "ErrorTrackingIssueCreatedWorkflow",
    "ErrorTrackingIssueReopenedWorkflow",
    "ErrorTrackingIssueSpikingWorkflow",
    "ErrorTrackingRecommendationsRefreshWorkflow",
    "ErrorTrackingSpikeEventCleanupWorkflow",
    "ErrorTrackingSymbolSetCleanupWorkflow",
    "ErrorTrackingWeeklyDigestWorkflow",
    "cleanup_spike_events_activity",
    "cleanup_symbol_sets_activity",
    "get_digest_orgs_activity",
    "get_team_batches_activity",
    "refresh_recommendations_batch_activity",
    "send_org_digest_activity",
]
