from typing import TYPE_CHECKING

from products.engineering_analytics.backend.logic.job_logs.activity import (
    FetchDepotJobLogWorkflow,
    FetchGithubJobLogWorkflow,
    fetch_and_emit_depot_job_log_activity,
    fetch_and_emit_job_log_activity,
)
from products.engineering_analytics.backend.logic.job_logs.coordinator import (
    GithubJobLogsCoordinatorWorkflow,
    discover_failed_depot_attempts_activity,
    discover_failed_jobs_activity,
)

if TYPE_CHECKING:
    from posthog.temporal.common.registration import ActivityDefinition

WORKFLOWS = [GithubJobLogsCoordinatorWorkflow, FetchGithubJobLogWorkflow, FetchDepotJobLogWorkflow]
ACTIVITIES: list[ActivityDefinition] = [
    discover_failed_jobs_activity,
    discover_failed_depot_attempts_activity,
    fetch_and_emit_job_log_activity,
    fetch_and_emit_depot_job_log_activity,
]
