"""Temporal wiring surface of the logs facade.

Core registers the logs alerting workflow on its workers and manages its
schedule through this module. Everything core's worker/schedule wiring
touches must be re-exported here — that keeps the wiring inside the contract
surface (``backend/facade/**``), so renaming or reshaping these entry points
correctly re-runs the full suite, while the implementations behind them stay
product-internal.
"""

from products.logs.backend.temporal import ACTIVITIES, WORKFLOWS, LogsAlertCheckWorkflow
from products.logs.backend.temporal.activities import CheckAlertsInput
from products.logs.backend.temporal.constants import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME
from products.logs.backend.temporal.metrics import (
    LOGS_ALERTING_COUNT_HISTOGRAM_BUCKETS,
    LOGS_ALERTING_COUNT_HISTOGRAM_METRICS,
    LOGS_ALERTING_LATENCY_HISTOGRAM_BUCKETS,
    LOGS_ALERTING_LATENCY_HISTOGRAM_METRICS,
    LogsAlertingMetricsInterceptor,
)

__all__ = [
    "ACTIVITIES",
    "WORKFLOWS",
    "LogsAlertCheckWorkflow",
    "CheckAlertsInput",
    "SCHEDULE_CRON",
    "SCHEDULE_ID",
    "WORKFLOW_NAME",
    "LOGS_ALERTING_COUNT_HISTOGRAM_BUCKETS",
    "LOGS_ALERTING_COUNT_HISTOGRAM_METRICS",
    "LOGS_ALERTING_LATENCY_HISTOGRAM_BUCKETS",
    "LOGS_ALERTING_LATENCY_HISTOGRAM_METRICS",
    "LogsAlertingMetricsInterceptor",
]
