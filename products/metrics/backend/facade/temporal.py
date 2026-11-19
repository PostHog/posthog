"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.metrics.backend.temporal import ACTIVITIES, WORKFLOWS
from products.metrics.backend.temporal.alert_evaluate import (
    METRICS_ALERT_EVALUATION_ACTIVITIES,
    METRICS_ALERT_EVALUATION_WORKFLOWS,
)
from products.metrics.backend.temporal.recording_rules import (
    create_metrics_recording_rules_schedule as create_metrics_recording_rules_schedule,
)
from products.metrics.backend.temporal.schedule import (
    create_suggested_dashboards_discovery_schedule as create_suggested_dashboards_discovery_schedule,
)

__all__ = [
    "ACTIVITIES",
    "METRICS_ALERT_EVALUATION_ACTIVITIES",
    "METRICS_ALERT_EVALUATION_WORKFLOWS",
    "WORKFLOWS",
    "create_metrics_recording_rules_schedule",
    "create_suggested_dashboards_discovery_schedule",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(METRICS_ALERT_EVALUATION_WORKFLOWS),
            activities=tuple(METRICS_ALERT_EVALUATION_ACTIVITIES),
        ),
    ),
    schedules=(create_suggested_dashboards_discovery_schedule, create_metrics_recording_rules_schedule),
)
