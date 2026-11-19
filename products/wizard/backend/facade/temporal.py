from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.wizard.backend.temporal import ACTIVITIES, WORKFLOWS

__all__ = ["ACTIVITIES", "WORKFLOWS"]

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="WIZARD_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),),
)
