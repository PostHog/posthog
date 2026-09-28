import posthoganalytics
from temporalio import activity

from posthog.temporal.common.utils import close_db_connections

from products.error_tracking.backend.logic.repo_paths.metrics import record_job_outcome
from products.error_tracking.backend.logic.repo_paths.release_files import (
    RepoPathsRetryableError,
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
        outcome = store_release_file_list(inputs.team_id, inputs.release_id)
    except RepoPathsRetryableError as error:
        # Count a job once, by its final attempt, so a retried timeout is not counted three times.
        if activity.info().attempt >= ACTIVITY_RETRY_POLICY.maximum_attempts:
            record_job_outcome(error.outcome)
        raise
    # A deferred job is counted by the try that ends it. The egress limiter counts each denial.
    if outcome != BUDGET_EXHAUSTED_OUTCOME or inputs.last_try:
        record_job_outcome(outcome)
    return outcome


ACTIVITIES = [store_release_file_list_activity]
