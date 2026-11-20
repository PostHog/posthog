from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.replay.backend.temporal.export_recordings import EXPORT_RECORDINGS_ACTIVITIES, EXPORT_RECORDINGS_WORKFLOWS

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="SESSION_REPLAY_TASK_QUEUE",
            workflows=tuple(EXPORT_RECORDINGS_WORKFLOWS),
            activities=tuple(EXPORT_RECORDINGS_ACTIVITIES),
        ),
    ),
)
