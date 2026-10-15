import json

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ReviewIssueFinding
from products.review_hog.backend.reviewer.constants import (
    DEFAULT_URGENCY_THRESHOLD,
    REVIEW_MODE_FLASH,
    REVIEW_MODE_FULL,
)
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.issues_review import IssuePriority
from products.review_hog.backend.reviewer.persistence import upsert_review_report
from products.review_hog.backend.reviewer.tools.publish_review import PublishOutcome
from products.signals.backend.artefact_attribution import ArtefactAttribution

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
    def _report(
        self,
        *,
        run_count: int,
        head_sha: str = "sha7",
        completed_head_sha: str | None = None,
        markdown: str = "# body",
        run_urgency_threshold: str | None = None,
    ) -> str:
        report_id = upsert_review_report(
            team_id=self.team.id, repository="PostHog/posthog", pr_url=_URL, pr_metadata=_meta()
        )
        ReviewReport.objects.for_team(self.team.id).filter(id=report_id).update(
            run_count=run_count,
            head_sha=head_sha,
            completed_head_sha=completed_head_sha,
            report_markdown=markdown,
            run_urgency_threshold=run_urgency_threshold,
        )
        return report_id

    def _finding_mode(self, report_id: str, run_index: int, mode: str | None) -> None:
        ReviewReportArtefact.append_finding(
            team_id=self.team.id,
            report_id=report_id,
            content=ReviewIssueFinding(
                issue_key=f"r{run_index}:a.py:1:logic:1",
                run_index=run_index,
                validation_context=json.dumps({"review_mode": mode}) if mode is not None else None,
                title="Missing guard",
                file="a.py",
                body="The value can be absent.",
                suggestion="Check the value before using it.",
                priority=IssuePriority.SHOULD_FIX,
            ),
            attribution=ArtefactAttribution.system(),
        )

    def test_errors_when_no_review_exists(self) -> None:
        with pytest.raises(CommandError, match="No review found"):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

    def test_errors_when_review_never_completed(self) -> None:
        # A report row exists but no turn finished (run_count 0) — there is nothing persisted to post.
        self._report(run_count=0)
        with pytest.raises(CommandError, match="hasn't completed a run"):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

    @parameterized.expand(
        [
            (None, None, REVIEW_MODE_FULL),
            (None, REVIEW_MODE_FLASH, REVIEW_MODE_FLASH),
            (REVIEW_MODE_FLASH, REVIEW_MODE_FLASH, REVIEW_MODE_FLASH),
            (None, REVIEW_MODE_FULL, REVIEW_MODE_FULL),
        ]
    )
    @patch(_STALE, return_value=None)
    @patch(_PUBLISH, return_value=PublishOutcome(posted=True))
    def test_publishes_latest_completed_run_with_no_recompute(
        self,
        review_mode: str | None,
        stored_mode: str | None,
        expected_mode: str,
        mock_publish: MagicMock,
        _stale: MagicMock,
    ) -> None:
        # The standalone publish targets the last completed turn — run_index == run_count, at the
        # report's reviewed head_sha — and reuses the shared DB-driven publish path (no workflow).
        report_id = self._report(run_count=2, head_sha="sha7")
        earlier_mode = REVIEW_MODE_FULL if expected_mode == REVIEW_MODE_FLASH else REVIEW_MODE_FLASH
        self._finding_mode(report_id, 1, earlier_mode)
        self._finding_mode(report_id, 2, stored_mode)
        integration = MagicMock()
        integration.get_access_token.return_value = "tok"
        integration.github_installation_id = "9876543"

        args = ["--review-mode", review_mode] if review_mode else []
        with patch(_INTEGRATION, return_value=integration):
            call_command("publish_review", *args, pr_url=_URL, team_id=self.team.id)

        assert mock_publish.call_count == 1
        kwargs = mock_publish.call_args.kwargs
        assert kwargs["report_id"] == report_id
        assert kwargs["run_index"] == 2
        assert kwargs["head_sha"] == "sha7"
        assert kwargs["review_mode"] == expected_mode
        # The installation id rides along so the publish calls are metered against the right budget.
        assert kwargs["installation_id"] == "9876543"

    @parameterized.expand([(REVIEW_MODE_FLASH, REVIEW_MODE_FULL), (REVIEW_MODE_FULL, REVIEW_MODE_FLASH)])
    def test_rejects_a_mode_that_differs_from_the_stored_review(self, stored_mode: str, requested_mode: str) -> None:
        report_id = self._report(run_count=1)
        self._finding_mode(report_id, 1, stored_mode)
        with patch(_INTEGRATION) as integration:
            with pytest.raises(CommandError, match=f"The stored review used {stored_mode} mode"):
                call_command("publish_review", "--review-mode", requested_mode, pr_url=_URL, team_id=self.team.id)
        integration.assert_not_called()

    @patch(_STALE, return_value=None)
    @patch(_PUBLISH, return_value=PublishOutcome(posted=True))
    def test_publishes_the_head_the_completed_turn_reviewed(self, mock_publish: MagicMock, _stale: MagicMock) -> None:
        # `head_sha` advances when a turn STARTS, so a turn that fetched a new commit and then failed
        # leaves it past the findings this command publishes. Pairing turn 2 with that newer head
        # would position its comments against a diff it never reviewed and record the published-head
        # watermark there, which then suppresses the publish of a later turn at that same commit.
        self._report(run_count=2, head_sha="sha9", completed_head_sha="sha7")
        integration = MagicMock()
        integration.get_access_token.return_value = "tok"
        integration.github_installation_id = "9876543"

        with patch(_INTEGRATION, return_value=integration):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

        kwargs = mock_publish.call_args.kwargs
        assert (kwargs["run_index"], kwargs["head_sha"]) == (2, "sha7")

    @parameterized.expand(
        [
            ("stamped", "must_fix", IssuePriority.MUST_FIX),
            ("unstamped", None, DEFAULT_URGENCY_THRESHOLD),
        ]
    )
    @patch(_STALE, return_value=None)
    @patch(_PUBLISH, return_value=PublishOutcome(posted=True))
    def test_republishes_under_the_threshold_the_run_used(
        self,
        _name: str,
        stamped: str | None,
        expected: IssuePriority,
        mock_publish: MagicMock,
        _stale: MagicMock,
    ) -> None:
        # The stored body's tally was rendered under the run's threshold, so republishing has to gate the
        # inline comments by that same threshold — publishing at the broader default would post findings
        # the frozen tally doesn't count. A row from before the column existed falls back to the default.
        self._report(run_count=1, run_urgency_threshold=stamped)
        integration = MagicMock()
        integration.get_access_token.return_value = "tok"
        integration.github_installation_id = "9876543"

        with patch(_INTEGRATION, return_value=integration):
            call_command("publish_review", pr_url=_URL, team_id=self.team.id)

        assert mock_publish.call_args.kwargs["urgency_threshold"] == expected
