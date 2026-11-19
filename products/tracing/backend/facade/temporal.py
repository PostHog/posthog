"""Temporal wiring re-exports: the only path core may use to register this product's workflows and activities."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.tracing.backend.temporal.alert_evaluate import (
    TRACES_ALERT_EVALUATION_ACTIVITIES,
    TRACES_ALERT_EVALUATION_WORKFLOWS,
)

__all__ = ["TRACES_ALERT_EVALUATION_ACTIVITIES", "TRACES_ALERT_EVALUATION_WORKFLOWS"]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="ALERTS_PLATFORM_EVALUATION_TASK_QUEUE",
            workflows=tuple(TRACES_ALERT_EVALUATION_WORKFLOWS),
            activities=tuple(TRACES_ALERT_EVALUATION_ACTIVITIES),
        ),
    ),
)
