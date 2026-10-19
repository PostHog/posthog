"""Temporal wiring re-exports: the worker registers ``WORKFLOWS``/``ACTIVITIES`` on ``settings.TASKS_TASK_QUEUE``.

Kept apart from ``facade/api.py`` so ``temporalio`` stays off the light data-surface import path.
"""

from products.slack_app.backend.temporal import SLACK_APP_ACTIVITIES
from products.slack_app.backend.temporal.posthog_code_slack_mention_command import (
    PostHogCodeSlackMentionCommandWorkflow,
)
from products.slack_app.backend.temporal.posthog_slack_inbox_onboarding import PostHogSlackInboxOnboardingWorkflow
from products.slack_app.backend.temporal.slack_app_fork import SlackAppForkThreadWorkflow
from products.slack_app.backend.temporal.slack_app_mention import SlackAppMentionWorkflow
from products.slack_app.backend.temporal.slack_app_mention_processing import SlackAppMentionProcessingWorkflow
from products.slack_app.backend.temporal.slack_app_unfurl_charts import SlackAppUnfurlChartsWorkflow

WORKFLOWS = [
    SlackAppMentionProcessingWorkflow,
    SlackAppMentionWorkflow,
    PostHogCodeSlackMentionCommandWorkflow,
    SlackAppForkThreadWorkflow,
    PostHogSlackInboxOnboardingWorkflow,
    SlackAppUnfurlChartsWorkflow,
]

ACTIVITIES = [*SLACK_APP_ACTIVITIES]

__all__ = ["ACTIVITIES", "WORKFLOWS"]
