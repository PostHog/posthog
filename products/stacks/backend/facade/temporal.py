"""The stacks Temporal code that core's worker and scheduler host, on the queue only the stacks worker image polls.

Kept apart from ``facade/api.py`` so ``temporalio`` stays off the light data-surface import path.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.stacks.backend.temporal.registry import ACTIVITIES, WORKFLOWS
from products.stacks.backend.temporal.schedule import create_stacks_cleanup_schedule

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="STACKS_TASK_QUEUE", workflows=WORKFLOWS, activities=ACTIVITIES),),
    schedules=(create_stacks_cleanup_schedule,),
)
