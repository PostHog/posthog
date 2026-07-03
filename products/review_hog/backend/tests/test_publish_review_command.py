import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.tools.publish_review import PublishOutcome

_PUBLISH = "products.review_hog.backend.management.commands.publish_review.publish_persisted_review"
_INTEGRATION = (
    "products.review_hog.backend.management.commands.publish_review.GitHubIntegration.first_for_team_repository"
)
_STALE = "products.review_hog.backend.management.commands.publish_review._stale_head_warning"
_URL = "https://github.com/PostHog/posthog/pull/7"


def _meta() -> PRMetadata:
    return PRMetadata(
        number=7,
        title="t",
        state="open",
        draft=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        author="a",
        base_branch="main",
        head_branch="feat",
        head_sha="sha7",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


class TestPublishReviewCommand(BaseTest):
    def _report(self, *, run_count: int, head_sha: str = "sha7", markdown: str = "# body") -> str:
        report_id = upsert_review_report(
            team_id=self.team.id, repository="PostHog/posthog", pr_url=_URL, pr_metadata=_meta()
        )
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
            run_count=run_count, head_sha=head_sha, report_markdown=markdown
        )
        return report_id

    def test_errors_when_no_review_exists(self) -> None:
        with pytest.raises(CommandError, match="No review found"):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

    def test_errors_when_review_never_completed(self) -> None:
        # A report row exists but no turn finished (run_count 0) — there is nothing persisted to post.
        self._report(run_count=0)
        with pytest.raises(CommandError, match="hasn't completed a run"):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

    @patch(_STALE, return_value=None)
    @patch(_PUBLISH, return_value=PublishOutcome(posted=True))
    def test_publishes_latest_completed_run_with_no_recompute(self, mock_publish: MagicMock, _stale: MagicMock) -> None:
        # The standalone publish targets the last completed turn — run_index == run_count, at the
        # report's reviewed head_sha — and reuses the shared DB-driven publish path (no workflow).
        report_id = self._report(run_count=2, head_sha="sha7")
        integration = MagicMock()
        integration.get_access_token.return_value = "tok"

        with patch(_INTEGRATION, return_value=integration):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

        assert mock_publish.call_count == 1
        kwargs = mock_publish.call_args.kwargs
        assert kwargs["report_id"] == report_id
        assert kwargs["run_index"] == 2
        assert kwargs["head_sha"] == "sha7"
