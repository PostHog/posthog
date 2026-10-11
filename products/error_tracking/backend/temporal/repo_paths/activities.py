import posthoganalytics
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.logic.repo_paths.job_report import report_finished_job
from products.error_tracking.backend.logic.repo_paths.release_files import (
    ReleaseFileListResult,
    RepoPathsRetryableError,
    RetryableOutcome,
    store_release_file_list,
)
from products.error_tracking.backend.temporal.repo_paths.types import (
    BUDGET_EXHAUSTED_OUTCOME,
    StoreReleaseFileListInputs,
)
from products.error_tracking.backend.temporal.repo_paths.workflow import ACTIVITY_RETRY_POLICY


@activity.defn
@posthoganalytics.scoped()
@close_db_connections
def store_release_file_list_activity(inputs: StoreReleaseFileListInputs) -> str:
    try:
        result = store_release_file_list(inputs.team_id, inputs.release_id)
    except Exception as error:
        # Count a job once, by its final attempt, so a retried timeout is not counted three times.
        if activity.info().attempt >= ACTIVITY_RETRY_POLICY.maximum_attempts:
            outcome: RetryableOutcome = error.outcome if isinstance(error, RepoPathsRetryableError) else "error"
            report_finished_job(inputs.team_id, inputs.release_id, ReleaseFileListResult(outcome=outcome))
        raise
    # A deferred job is counted by the try that ends it. The egress limiter counts each denial.
    if result.outcome != BUDGET_EXHAUSTED_OUTCOME or inputs.last_try:
        report_finished_job(inputs.team_id, inputs.release_id, result)
    return result.outcome


ACTIVITIES = [store_release_file_list_activity]
