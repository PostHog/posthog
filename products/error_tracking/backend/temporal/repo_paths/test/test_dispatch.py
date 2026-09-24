from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized
from temporalio.common import WorkflowIDReusePolicy

from products.error_tracking.backend.models import ErrorTrackingRelease
from products.error_tracking.backend.temporal.repo_paths.dispatch import start_repo_paths_workflow

COMMIT = "0123456789abcdef0123456789abcdef01234567"


class TestStartRepoPathsWorkflow(BaseTest):
    @parameterized.expand([("flag_on", True), ("flag_off", False)])
    def test_starts_one_workflow_per_commit_for_flagged_teams(self, _name: str, flag_enabled: bool) -> None:
        release = ErrorTrackingRelease.objects.create(
            team=self.team,
            hash_id="shop-1",
            version="1.0.0",
            project="shop",
            metadata={"git": {"remote_url": "git@github.com:acme/shop.git", "commit_id": COMMIT}},
        )
        temporal = MagicMock()
        temporal.start_workflow = AsyncMock()

        with (
            patch(
                "products.error_tracking.backend.logic.repo_paths.release_repo.feature_enabled_or_false",
                return_value=flag_enabled,
            ),
            patch(
                "products.error_tracking.backend.temporal.repo_paths.dispatch.async_connect",
                AsyncMock(return_value=temporal),
            ),
        ):
            start_repo_paths_workflow(team_id=self.team.id, release_id=str(release.id))

        if not flag_enabled:
            temporal.start_workflow.assert_not_called()
            return
        temporal.start_workflow.assert_awaited_once()
        kwargs = temporal.start_workflow.await_args.kwargs
        assert kwargs["id"] == f"error-tracking-repo-paths:{self.team.id}:github.com/acme/shop:{COMMIT}"
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
