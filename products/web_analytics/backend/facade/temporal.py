"""The web analytics Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.web_analytics.backend.temporal import (
    ACTIVITIES as WA_DIGEST_ACTIVITIES,
    WORKFLOWS as WA_DIGEST_WORKFLOWS,
)
from products.web_analytics.backend.temporal.page_history.registry import (
    ACTIVITIES as HEATMAP_PAGE_HISTORY_ACTIVITIES,
    WORKFLOWS as HEATMAP_PAGE_HISTORY_WORKFLOWS,
)
from products.web_analytics.backend.temporal.page_history.schedule import create_heatmap_page_history_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        # The web-analytics digests share this queue with the PostHog-wide weekly digest: both are
        # weekly crons with the same shape, and the messaging queue they used to sit on has no other
        # workflows left, so a dedicated fleet for them isn't worth its reserved capacity.
        QueueBinding(
            queue_setting="WEEKLY_DIGEST_TASK_QUEUE",
            workflows=tuple(WA_DIGEST_WORKFLOWS),
            activities=tuple(WA_DIGEST_ACTIVITIES),
        ),
        QueueBinding(
            queue_setting="WEB_ANALYTICS_TASK_QUEUE",
            workflows=tuple(HEATMAP_PAGE_HISTORY_WORKFLOWS),
            activities=tuple(HEATMAP_PAGE_HISTORY_ACTIVITIES),
        ),
    ),
    schedules=(create_heatmap_page_history_schedule,),
)
