from products.reaperhog.backend.temporal.activities import (
    harvest_activity,
    scan_activity,
    sync_activity,
    verify_activity,
)
from products.reaperhog.backend.temporal.workflow import ReapScopeWorkflow

WORKFLOWS = [ReapScopeWorkflow]

ACTIVITIES = [scan_activity, verify_activity, sync_activity, harvest_activity]
