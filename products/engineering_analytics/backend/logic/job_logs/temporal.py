"""Workflow + activity registration lists for the job-logs worker.

Registered on ``settings.GENERAL_PURPOSE_TASK_QUEUE`` (the queue the schedule targets) via the
product facade in ``backend/facade/temporal.py``.
"""

from products.engineering_analytics.backend.logic.job_logs.activity import (
    FetchGithubJobLogWorkflow,
    fetch_and_emit_job_log_activity,
)
from products.engineering_analytics.backend.logic.job_logs.coordinator import (
    GithubJobLogsCoordinatorWorkflow,
    discover_failed_jobs_activity,
)

WORKFLOWS = [GithubJobLogsCoordinatorWorkflow, FetchGithubJobLogWorkflow]
ACTIVITIES = [discover_failed_jobs_activity, fetch_and_emit_job_log_activity]
