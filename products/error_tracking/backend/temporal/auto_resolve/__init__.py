from products.error_tracking.backend.temporal.auto_resolve.activities import (
    list_auto_resolve_teams,
    resolve_quiet_issues,
    sync_pending_auto_resolves,
)
from products.error_tracking.backend.temporal.auto_resolve.workflow import ErrorTrackingAutoResolveWorkflow

WORKFLOWS = [ErrorTrackingAutoResolveWorkflow]
ACTIVITIES = [list_auto_resolve_teams, resolve_quiet_issues, sync_pending_auto_resolves]
