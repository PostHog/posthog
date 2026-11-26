"""Temporal wiring: the worker registers ``TEMPORAL`` on ``settings.TASKS_TASK_QUEUE``.

Kept apart from ``facade/api.py`` so ``temporalio`` stays off the light data-surface import path.
"""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.slack_app.backend.temporal.registry import (
    ACTIVITIES as _ACTIVITIES,
    WORKFLOWS as _WORKFLOWS,
)
from products.slack_app.backend.temporal.schedule import create_slack_app_daily_focus_sweep_schedule

TEMPORAL = TemporalRegistration(
    queues=(
        # PostHog Desktop Slack workflows share this queue with ProcessTaskWorkflow,
        # which they hand off to once a repo is picked.
        QueueBinding(queue_setting="TASKS_TASK_QUEUE", workflows=tuple(_WORKFLOWS), activities=tuple(_ACTIVITIES)),
    ),
    schedules=(create_slack_app_daily_focus_sweep_schedule,),
)
