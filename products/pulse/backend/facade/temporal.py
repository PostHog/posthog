"""The pulse Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.pulse.backend.temporal.registry import (
    ACTIVITIES as PULSE_ACTIVITIES,
    WORKFLOWS as PULSE_WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="ANALYTICS_PLATFORM_TASK_QUEUE",
            workflows=tuple(PULSE_WORKFLOWS),
            activities=tuple(PULSE_ACTIVITIES),
        ),
    ),
)
