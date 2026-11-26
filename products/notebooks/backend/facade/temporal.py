"""
Facade re-exports for Temporal wiring.

The worker bootstrap (`start_temporal_worker`) registers notebook workflows and
activities through these re-exports rather than importing ``backend.temporal``
directly.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal.registry import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
)
