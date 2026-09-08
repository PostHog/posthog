"""Facade re-exports for the metrics alerting Temporal wiring.

Core registers this product's workflow + activities with the Temporal worker
(``posthog/management/commands/start_temporal_worker.py``) and its schedule
(``posthog/temporal/metrics_alerting/schedule.py``). Keep the temporalio-heavy
imports behind this seam, off the ``facade/api.py`` path.
"""

from products.metrics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.metrics.backend.temporal.activities import DiscoverMetricsAlertsInput
from products.metrics.backend.temporal.constants import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "DiscoverMetricsAlertsInput",
    "SCHEDULE_CRON",
    "SCHEDULE_ID",
    "WORKFLOW_NAME",
]
