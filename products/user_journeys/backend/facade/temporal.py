"""The user journeys Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``. Kept apart from ``facade/api.py`` so ``temporalio``
never lands on the light data-surface import path.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.user_journeys.backend.temporal import ACTIVITIES, WORKFLOWS
from products.user_journeys.backend.temporal.stale_runs import create_reap_stale_journey_runs_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
    schedules=(create_reap_stale_journey_runs_schedule,),
)
