import dataclasses

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from prometheus_client import REGISTRY
from temporalio.testing import ActivityEnvironment

from products.error_tracking.backend.logic.repo_paths.release_files import (
    ReleaseFileListResult,
    RepoPathsRetryableError,
    StoredFileList,
)
from products.error_tracking.backend.logic.repo_paths.release_repo import ReleaseRepo
from products.error_tracking.backend.logic.repo_paths.slug import RepoSlug
from products.error_tracking.backend.temporal.repo_paths.activities import store_release_file_list_activity
from products.error_tracking.backend.temporal.repo_paths.types import StoreReleaseFileListInputs
from products.error_tracking.backend.temporal.repo_paths.workflow import ACTIVITY_RETRY_POLICY

FINAL_ATTEMPT = ACTIVITY_RETRY_POLICY.maximum_attempts
COMMIT = "0123456789abcdef0123456789abcdef01234567"
STORE = "products.error_tracking.backend.temporal.repo_paths.activities.store_release_file_list"
CAPTURE = "products.error_tracking.backend.logic.repo_paths.job_report.ph_background_capture"


def _jobs(outcome: str) -> float:
    return REGISTRY.get_sample_value("error_tracking_repo_paths_jobs_total", {"outcome": outcome}) or 0.0


class TestStoreReleaseFileListActivity(BaseTest):
    def _inputs(self) -> StoreReleaseFileListInputs:
        return StoreReleaseFileListInputs(team_id=self.team.id, release_id="release", last_try=False)

    @parameterized.expand(
        [
            ("retried_timeout", RepoPathsRetryableError("timeout", "git timed out"), 1, "timeout", 0),
            ("last_timeout", RepoPathsRetryableError("timeout", "git timed out"), FINAL_ATTEMPT, "timeout", 1),
            ("last_unexpected_error", ConnectionError("object storage is down"), FINAL_ATTEMPT, "error", 1),
        ]
    )
    def test_a_failed_job_is_reported_once_by_its_final_attempt(
        self, _name: str, error: Exception, attempt: int, outcome: str, reported: int
    ) -> None:
        environment = ActivityEnvironment()
        environment.info = dataclasses.replace(environment.info, attempt=attempt)
        before = _jobs(outcome)

        with patch(STORE, side_effect=error), patch(CAPTURE) as capture, pytest.raises(type(error)):
            environment.run(store_release_file_list_activity, self._inputs())

        assert _jobs(outcome) - before == reported
        events = capture.return_value.call_args_list
        assert [(e.kwargs["properties"]["outcome"], e.kwargs["properties"]["success"]) for e in events] == [
            (outcome, False)
        ] * reported

    def test_a_stored_list_reports_its_size_to_the_team(self) -> None:
        result = ReleaseFileListResult(
            outcome="written",
            repo=ReleaseRepo(slug=RepoSlug(host="gitlab.example.com", path="acme/shop"), commit=COMMIT),
            provider="gitlab",
            stored=StoredFileList(
                path_count=3, stored_bytes=120, fetched_bytes=4096, fetch_seconds=1.5, removed_lists=1
            ),
        )

        with patch(STORE, return_value=result), patch(CAPTURE) as capture:
            assert ActivityEnvironment().run(store_release_file_list_activity, self._inputs()) == "written"

        capture.return_value.assert_called_once()
        event = capture.return_value.call_args.kwargs
        assert event["event"] == "error_tracking_release_file_list_stored"
        assert event["distinct_id"] == str(self.team.uuid)
        assert event["groups"]["project"] == str(self.team.uuid)
        assert event["groups"]["organization"] == str(self.organization.id)
        assert event["properties"] == {
            "success": True,
            "outcome": "written",
            "release_id": "release",
            "commit_id": COMMIT,
            "provider": "gitlab",
            "self_hosted": True,
            "path_count": 3,
            "stored_bytes": 120,
            "fetched_bytes": 4096,
            "fetch_seconds": 1.5,
            "removed_lists": 1,
        }
