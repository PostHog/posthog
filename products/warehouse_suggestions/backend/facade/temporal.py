"""Facade re-exports for Temporal wiring."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
from ..temporal.schedule import create_warehouse_suggestions_schedule as create_warehouse_suggestions_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="DATA_MODELING_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    schedules=(create_warehouse_suggestions_schedule,),
)
