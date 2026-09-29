import dataclasses

import pytest
from unittest.mock import patch

from prometheus_client import REGISTRY
from temporalio.testing import ActivityEnvironment

from products.error_tracking.backend.logic.repo_paths.release_files import RepoPathsRetryableError
from products.error_tracking.backend.temporal.repo_paths.activities import store_release_file_list_activity
from products.error_tracking.backend.temporal.repo_paths.types import StoreReleaseFileListInputs
from products.error_tracking.backend.temporal.repo_paths.workflow import ACTIVITY_RETRY_POLICY

FINAL_ATTEMPT = ACTIVITY_RETRY_POLICY.maximum_attempts


def _jobs(outcome: str) -> float:
    return REGISTRY.get_sample_value("error_tracking_repo_paths_jobs_total", {"outcome": outcome}) or 0.0


@pytest.mark.parametrize(
    "error, attempt, outcome, counted",
    [
        pytest.param(RepoPathsRetryableError("timeout", "git timed out"), 1, "timeout", 0, id="retried_timeout"),
        pytest.param(
            RepoPathsRetryableError("timeout", "git timed out"), FINAL_ATTEMPT, "timeout", 1, id="last_timeout"
        ),
        pytest.param(ConnectionError("object storage is down"), FINAL_ATTEMPT, "error", 1, id="last_unexpected_error"),
    ],
)
def test_a_failed_job_is_counted_once_by_its_final_attempt(
    error: Exception, attempt: int, outcome: str, counted: int
) -> None:
    environment = ActivityEnvironment()
    environment.info = dataclasses.replace(environment.info, attempt=attempt)
    before = _jobs(outcome)

    with (
        patch(
            "products.error_tracking.backend.temporal.repo_paths.activities.store_release_file_list",
            side_effect=error,
        ),
        pytest.raises(type(error)),
    ):
        environment.run(
            store_release_file_list_activity,
            StoreReleaseFileListInputs(team_id=1, release_id="release", last_try=False),
        )

    assert _jobs(outcome) - before == counted
