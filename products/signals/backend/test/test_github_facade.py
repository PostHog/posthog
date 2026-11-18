from unittest.mock import call, patch

from django.test import SimpleTestCase

from products.signals.backend.facade.github import refresh_pull_request_review_decisions


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
