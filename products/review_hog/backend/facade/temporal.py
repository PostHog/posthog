"""The PostHog Review Temporal code that core's worker and scheduler host.

Only core's Temporal loaders read ``TEMPORAL``. Kept apart from ``facade/api.py`` so ``temporalio``
never lands on the light data-surface import path.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.review_hog.backend.temporal import ACTIVITIES, WORKFLOWS
from products.review_hog.backend.temporal.outcomes_schedule import create_review_hog_finding_outcomes_schedule

TEMPORAL = TemporalRegistration(
    queues=(QueueBinding(queue_setting="VIDEO_EXPORT_TASK_QUEUE", workflows=WORKFLOWS, activities=ACTIVITIES),),
    schedules=(create_review_hog_finding_outcomes_schedule,),
)
