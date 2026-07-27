from products.logs.backend.temporal.retention_entitlements.activities import enforce_logs_retention_entitlements
from products.logs.backend.temporal.retention_entitlements.workflow import EnforceLogsRetentionEntitlementsWorkflow

WORKFLOWS: list = [EnforceLogsRetentionEntitlementsWorkflow]
ACTIVITIES: list = [enforce_logs_retention_entitlements]

__all__ = [
    "ACTIVITIES",
    "EnforceLogsRetentionEntitlementsWorkflow",
    "WORKFLOWS",
    "enforce_logs_retention_entitlements",
]
