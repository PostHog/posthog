"""Facade re-exports for the logs Temporal wiring.

Core registers this product's workflows + activities with the Temporal worker
(``posthog/management/commands/start_temporal_worker.py``) and registers its schedules.
That wiring crosses the boundary as objects and constants, not data, so re-export exactly
what core touches and keep the temporalio-heavy imports here, off the ``facade/api.py`` path.
"""

from posthog.temporal.common.registration import HistogramSpec, QueueBinding, TemporalRegistration

from products.logs.backend.temporal.alert_evaluate import (
    PLATFORM_SIGNAL_ACTIVITIES,
    PLATFORM_SIGNAL_WORKFLOWS,
    SOURCE_EVALUATION_ACTIVITIES,
    SOURCE_EVALUATION_WORKFLOWS,
)
from products.logs.backend.temporal.retention_entitlements import (
    ACTIVITIES as LOGS_RETENTION_ENTITLEMENTS_ACTIVITIES,
    WORKFLOWS as LOGS_RETENTION_ENTITLEMENTS_WORKFLOWS,
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
from products.logs.backend.temporal.volume_tick.schedule import disable_logs_volume_tick_schedule

__all__ = [
    "PLATFORM_SIGNAL_ACTIVITIES",
    "PLATFORM_SIGNAL_WORKFLOWS",
    "SOURCE_EVALUATION_ACTIVITIES",
    "SOURCE_EVALUATION_WORKFLOWS",
    "VOLUME_TICK_ACTIVITIES",
    "VOLUME_TICK_WORKFLOWS",
    "VOLUME_TICK_SCHEDULE_CRON",
    "VOLUME_TICK_SCHEDULE_ID",
    "VOLUME_TICK_WORKFLOW_NAME",
    "LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS",
    "LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS",
    "VolumeTickInput",
    "disable_logs_volume_tick_schedule",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE",
            workflows=tuple(LOGS_RETENTION_ENTITLEMENTS_WORKFLOWS),
            activities=tuple(LOGS_RETENTION_ENTITLEMENTS_ACTIVITIES),
        ),
        # Dedicated queue: the tick becomes the scan-heavy rollup writer.
        QueueBinding(
            queue_setting="LOGS_VOLUME_TICK_TASK_QUEUE",
            workflows=tuple(VOLUME_TICK_WORKFLOWS),
            activities=tuple(VOLUME_TICK_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(SOURCE_EVALUATION_WORKFLOWS),
            activities=tuple(SOURCE_EVALUATION_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_DELIVERY_TASK_QUEUE",
            workflows=tuple(PLATFORM_SIGNAL_WORKFLOWS),
            activities=tuple(PLATFORM_SIGNAL_ACTIVITIES),
        ),
    ),
    schedules=(disable_logs_volume_tick_schedule,),
    histograms=(
        *HistogramSpec.for_metrics(
            LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_METRICS, LOGS_VOLUME_TICK_LATENCY_HISTOGRAM_BUCKETS
        ),
    ),
)
