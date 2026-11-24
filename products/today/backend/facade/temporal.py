"""Temporal wiring re-exports: the only path core may use to register this product's workflows,
activities and schedule."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal.registry import (
    ACTIVITIES as _ACTIVITIES,
    WORKFLOWS as _WORKFLOWS,
)
from ..temporal.schedule import delete_today_briefing_schedule as delete_today_briefing_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(_WORKFLOWS), activities=tuple(_ACTIVITIES)
        ),
    ),
    schedules=(delete_today_briefing_schedule,),
)
