from products.logs.backend.temporal.activities import check_alerts_activity
from products.logs.backend.temporal.workflow import LogsAlertCheckWorkflow

WORKFLOWS: list = [LogsAlertCheckWorkflow]
ACTIVITIES: list = [check_alerts_activity]

__all__ = [
    "LogsAlertCheckWorkflow",
    "check_alerts_activity",
    "WORKFLOWS",
    "ACTIVITIES",
]
