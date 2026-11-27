"""The posthog ai Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.posthog_ai.backend.temporal.backfill import (
    ACTIVITIES as CONVERSATION_BACKFILL_ACTIVITIES,
    WORKFLOWS as CONVERSATION_BACKFILL_WORKFLOWS,
)

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE",
            workflows=tuple(CONVERSATION_BACKFILL_WORKFLOWS),
            activities=tuple(CONVERSATION_BACKFILL_ACTIVITIES),
        ),
    ),
)
