from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.test import SimpleTestCase

from posthog.models import Team

from products.signals.backend.facade.github import (
    PULL_REQUEST_STATE_REREAD_DELAY_SECONDS,
    refresh_pull_request_review_decisions,
    update_pull_request_assignments,
)
from products.signals.backend.models import SignalReportPullRequest


class TestRefreshPullRequestReviewDecisions(SimpleTestCase):
    @patch("products.signals.backend.tasks.refresh_pull_request_review_decision.delay")
    @patch("products.signals.backend.facade.github.installation_team_ids", return_value=[1, 2])
    def test_enqueues_remaining_teams_after_one_failure(self, _team_ids, enqueue) -> None:
        enqueue.side_effect = [RuntimeError("queue unavailable"), None]

        refresh_pull_request_review_decisions(
            {
                "repository": {"full_name": "example/app"},
                "pull_request": {"number": 42},
            }
        )

        assert enqueue.call_args_list == [
            call(team_id=1, repository="example/app", pr_number=42),
            call(team_id=2, repository="example/app", pr_number=42),
        ]


class TestUpdatePullRequestAssignments(BaseTest):
    @patch("products.signals.backend.tasks.refresh_linked_pull_request_state.apply_async")
    def test_state_webhook_rereads_github_for_teams_that_store_the_pull_request(self, reread) -> None:
        url = "https://github.com/example/app/pull/42"
        SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team, repository="example/app", number=42, url=url, state="draft"
        )
        other_team = Team.objects.create(organization=self.organization)

        with (
            patch(
                "products.signals.backend.facade.github.installation_team_ids",
                return_value=[self.team.id, other_team.id],
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            update_pull_request_assignments(
                {
                    "repository": {"full_name": "Example/App"},
                    "pull_request": {"number": 42, "html_url": url},
                },
                "draft",
            )

        reread.assert_called_once_with(args=(self.team.id, url), countdown=PULL_REQUEST_STATE_REREAD_DELAY_SECONDS)
