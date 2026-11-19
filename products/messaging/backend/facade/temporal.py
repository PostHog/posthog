"""Temporal workflows and activities the provider import worker registers."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.messaging.backend.temporal.registry import (
    ACTIVITIES as ACTIVITIES,
    WORKFLOWS as WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        # Messaging provider imports. MESSAGING_IMPORT_TASK_QUEUE defaults to the general-purpose queue name (so it
        # merges into that fleet until a dedicated worker exists).
        QueueBinding(
            queue_setting="MESSAGING_IMPORT_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)
        ),
    ),
)
