"""Facade re-exports for the tracing alerting Temporal wiring.

Core registers this product's workflow + activities with the Temporal worker
(``posthog/management/commands/start_temporal_worker.py``) and registers its
schedule (``posthog/temporal/tracing_alerting/schedule.py``). That wiring
crosses the boundary as objects and constants, not data, so re-export exactly
what core touches and keep the temporalio-heavy imports here, off the
``facade/api.py`` path.
"""

from products.tracing.backend.temporal import ACTIVITIES, WORKFLOWS
from products.tracing.backend.temporal.activities import CheckAlertsInput
from products.tracing.backend.temporal.constants import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "CheckAlertsInput",
    "SCHEDULE_CRON",
    "SCHEDULE_ID",
    "WORKFLOW_NAME",
]
