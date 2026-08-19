"""Facade re-exports for the logs alerting Temporal wiring.

Core registers this product's workflow + activities with the Temporal worker
(``posthog/management/commands/start_temporal_worker.py``), wires its metrics
interceptor (``posthog/temporal/common/worker.py``), and registers its schedule
(``posthog/temporal/logs_alerting/schedule.py``). That wiring crosses the boundary as
objects and constants, not data, so re-export exactly what core touches and keep the
temporalio-heavy imports here, off the ``facade/api.py`` path.
"""

from products.logs.backend.temporal import ACTIVITIES, WORKFLOWS
from products.logs.backend.temporal.activities import CheckAlertsInput
from products.logs.backend.temporal.constants import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME
from products.logs.backend.temporal.metrics import (
    LOGS_ALERTING_COUNT_HISTOGRAM_BUCKETS,
    LOGS_ALERTING_COUNT_HISTOGRAM_METRICS,
    LOGS_ALERTING_LATENCY_HISTOGRAM_BUCKETS,
    LOGS_ALERTING_LATENCY_HISTOGRAM_METRICS,
    LogsAlertingMetricsInterceptor,
)
from products.logs.backend.temporal.volume_tick import (
    ACTIVITIES as VOLUME_TICK_ACTIVITIES,
    WORKFLOWS as VOLUME_TICK_WORKFLOWS,
)
from products.logs.backend.temporal.volume_tick.activities import VolumeTickInput
from products.logs.backend.temporal.volume_tick.constants import (
    SCHEDULE_CRON as VOLUME_TICK_SCHEDULE_CRON,
    SCHEDULE_ID as VOLUME_TICK_SCHEDULE_ID,
    WORKFLOW_NAME as VOLUME_TICK_WORKFLOW_NAME,
)
from products.logs.backend.temporal.volume_tick.metrics import (
    LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS,
    LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS,
)
from products.logs.backend.temporal.volume_tick.schedule import create_logs_volume_tick_schedule

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "CheckAlertsInput",
    "SCHEDULE_CRON",
    "SCHEDULE_ID",
    "WORKFLOW_NAME",
    "VOLUME_TICK_ACTIVITIES",
    "VOLUME_TICK_WORKFLOWS",
    "VOLUME_TICK_SCHEDULE_CRON",
    "VOLUME_TICK_SCHEDULE_ID",
    "VOLUME_TICK_WORKFLOW_NAME",
    "LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS",
    "LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS",
    "VolumeTickInput",
    "create_logs_volume_tick_schedule",
    "LOGS_ALERTING_COUNT_HISTOGRAM_BUCKETS",
    "LOGS_ALERTING_COUNT_HISTOGRAM_METRICS",
    "LOGS_ALERTING_LATENCY_HISTOGRAM_BUCKETS",
    "LOGS_ALERTING_LATENCY_HISTOGRAM_METRICS",
    "LogsAlertingMetricsInterceptor",
]
