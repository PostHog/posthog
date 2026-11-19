from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.knowledge_writer.backend.temporal import ACTIVITIES, WORKFLOWS
from products.knowledge_writer.backend.temporal.reconcile_schedule import (
    create_knowledge_writer_merge_reconcile_schedule,
)

__all__ = ["ACTIVITIES", "WORKFLOWS", "create_knowledge_writer_merge_reconcile_schedule"]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(queue_setting="VIDEO_EXPORT_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),
    ),
    schedules=(create_knowledge_writer_merge_reconcile_schedule,),
)
