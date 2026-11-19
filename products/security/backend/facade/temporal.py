from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from ..temporal import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)
from ..temporal.schedule import (
    create_sync_access_rules_schedule as create_sync_access_rules_schedule,
    start_sync_now as start_sync_now,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    schedules=(create_sync_access_rules_schedule,),
)
