"""Temporal wiring re-exports: the worker registers ``WORKFLOWS``/``ACTIVITIES`` on ``settings.TASKS_TASK_QUEUE``.

Kept apart from ``facade/api.py`` so ``temporalio`` stays off the light data-surface import path.
"""

from collections.abc import Callable

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.slack_app.backend.temporal import SLACK_APP_ACTIVITIES
from products.slack_app.backend.temporal.posthog_code_slack_mention_command import (
    PostHogCodeSlackMentionCommandWorkflow,
)
from products.slack_app.backend.temporal.posthog_slack_inbox_onboarding import PostHogSlackInboxOnboardingWorkflow
from products.slack_app.backend.temporal.schedule import create_slack_app_daily_focus_sweep_schedule
from products.slack_app.backend.temporal.slack_app_fork import SlackAppForkThreadWorkflow
from products.slack_app.backend.temporal.slack_app_mention import SlackAppMentionWorkflow
from products.slack_app.backend.temporal.slack_app_mention_processing import SlackAppMentionProcessingWorkflow
from products.slack_app.backend.temporal.slack_app_onboarding import SlackAppOnboardingWorkflow
from products.slack_app.backend.temporal.slack_app_unfurl_charts import SlackAppUnfurlChartsWorkflow
from products.slack_app.backend.temporal.slack_app_work_focus import (
    SlackAppDailyFocusSweepWorkflow,
    SlackAppWorkFocusWorkflow,
)

WORKFLOWS = [
    SlackAppMentionProcessingWorkflow,
    SlackAppMentionWorkflow,
    PostHogCodeSlackMentionCommandWorkflow,
    SlackAppForkThreadWorkflow,
    PostHogSlackInboxOnboardingWorkflow,
    SlackAppUnfurlChartsWorkflow,
    SlackAppOnboardingWorkflow,
    SlackAppWorkFocusWorkflow,
    SlackAppDailyFocusSweepWorkflow,
]

ACTIVITIES: list[Callable[..., object]] = [*SLACK_APP_ACTIVITIES]

__all__ = ["ACTIVITIES", "WORKFLOWS"]

TEMPORAL = TemporalRegistration(
    queues=(
        # PostHog Desktop Slack workflows share this queue with ProcessTaskWorkflow,
        # which they hand off to once a repo is picked.
        QueueBinding(queue_setting="TASKS_TASK_QUEUE", workflows=tuple(WORKFLOWS), activities=tuple(ACTIVITIES)),
    ),
    schedules=(create_slack_app_daily_focus_sweep_schedule,),
)
