"""The Temporal workflows, activities and schedules that core registers for this product."""

from posthog.temporal.common.registration import QueueBinding, TemporalRegistration

from products.engineering_analytics.backend.logic.job_logs.schedule import create_github_job_logs_coordinator_schedule
from products.engineering_analytics.backend.logic.job_logs.temporal import (
    ACTIVITIES as JOB_LOGS_ACTIVITIES,
    WORKFLOWS as JOB_LOGS_WORKFLOWS,
)
from products.engineering_analytics.backend.logic.signals.schedule import create_ci_signals_coordinator_schedule
from products.engineering_analytics.backend.logic.signals.temporal import (
    ACTIVITIES as CI_SIGNALS_ACTIVITIES,
    WORKFLOWS as CI_SIGNALS_WORKFLOWS,
)

__all__ = [
    "JOB_LOGS_ACTIVITIES",
    "JOB_LOGS_WORKFLOWS",
    "create_github_job_logs_coordinator_schedule",
    "CI_SIGNALS_ACTIVITIES",
    "CI_SIGNALS_WORKFLOWS",
    "create_ci_signals_coordinator_schedule",
]

TEMPORAL = TemporalRegistration(
    queues=(
        QueueBinding(
            queue_setting="GENERAL_PURPOSE_TASK_QUEUE",
            workflows=(*JOB_LOGS_WORKFLOWS, *CI_SIGNALS_WORKFLOWS),
            activities=(*JOB_LOGS_ACTIVITIES, *CI_SIGNALS_ACTIVITIES),
        ),
    ),
    schedules=(create_github_job_logs_coordinator_schedule, create_ci_signals_coordinator_schedule),
)
