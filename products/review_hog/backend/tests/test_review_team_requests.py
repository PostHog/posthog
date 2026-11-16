import dataclasses

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.integration import Integration

from products.review_hog.backend.models import ReviewInstallationClaim, ReviewReport, ReviewRepository
from products.review_hog.backend.review_team_requests import ReviewTeamRequest
from products.review_hog.backend.tasks import process_review_team_request

_INSTALLATION_ID = "1234"
_REPO_ID = 5001
_REQUESTER_ID = 4242
_HEAD_SHA = "a" * 40
_START = "products.review_hog.backend.requested_reviews.start_review_pr_workflow"
_BUSY = "products.review_hog.backend.requested_reviews.workflow_running"
_META = "products.review_hog.backend.requested_reviews.fetch_pr_metadata"
_ACCESS = "posthog.models.integration.GitHubIntegration.first_for_team_repository"
_REQUEST = ReviewTeamRequest(
    installation_id=_INSTALLATION_ID,
    repository="PostHog/posthog",
    github_repo_id=_REPO_ID,
    pr_number=42,
    requester_github_id=_REQUESTER_ID,
    requester_login="OctoCat",
)


class TestReviewTeamRequest(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id=_INSTALLATION_ID,
            config={"installation_id": _INSTALLATION_ID, "account": {"name": "PostHog"}},
            created_by=self.user,
        )
        ReviewInstallationClaim.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, scope=ReviewInstallationClaim.Scope.SELECTED
        )
        ReviewRepository.objects.for_team(self.team.id).create(
            team=self.team, installation_id=_INSTALLATION_ID, full_name="PostHog/posthog", selected=True
        )
        self.github_link = UserSocialAuth.objects.create(user=self.user, provider="github", uid=str(_REQUESTER_ID))
        self.github = MagicMock()
        self.github.get_collaborator_permission.return_value = "write"
        self.github.comment_on_pull_request.return_value = {"success": True}
        self.github.api_request.return_value = MagicMock(status_code=200)
        self.enterContext(patch(_ACCESS, return_value=self.github))
        self.enterContext(patch(_META, return_value=MagicMock(is_fork=False, state="open", head_sha=_HEAD_SHA)))
        self.enterContext(patch(_BUSY, return_value=False))
        self.enterContext(patch("posthoganalytics.feature_enabled", return_value=True))
        self.start = self.enterContext(patch(_START, return_value="wf-1"))

    def _replies(self) -> list[str]:
        return [call.args[2] for call in self.github.comment_on_pull_request.call_args_list]

    def _team_request_removed(self) -> bool:
        return any(
            call.args[0] == "DELETE" and call.kwargs["json_body"]["team_reviewers"] == ["posthog-review"]
            for call in self.github.api_request.call_args_list
        )

    def test_a_linked_writer_gets_a_review_as_themselves_and_the_request_is_cleared(self) -> None:
        process_review_team_request.run(**dataclasses.asdict(_REQUEST))

        assert self.start.call_args.kwargs["trigger_source"] == "review_request"
        assert self.start.call_args.kwargs["user_id"] == self.user.id
        assert self.start.call_args.kwargs["review_mode"] == "flash"
        assert self._replies() == []
        assert self._team_request_removed()

    @parameterized.expand(
        [
            ("no_write_access", "You need write access to this repository"),
            ("unlinked", "isn't linked to a PostHog account"),
            ("already_reviewed", "PostHog Review already reviewed the current commit."),
        ]
    )
    def test_a_request_that_starts_no_review_answers_and_clears_the_request(
        self, change: str, expected_reply: str
    ) -> None:
        if change == "no_write_access":
            self.github.get_collaborator_permission.return_value = "read"
        elif change == "unlinked":
            self.github_link.delete()
        else:
            ReviewReport.objects.for_team(self.team.id).create(
                team=self.team,
                repository="PostHog/posthog",
                pr_number=42,
                head_branch="feature",
                base_branch="master",
                published_heads_by_mode={"flash": _HEAD_SHA},
            )

        _REQUEST.start(final_attempt=False)

        self.start.assert_not_called()
        assert len(self._replies()) == 1 and expected_reply in self._replies()[0]
        assert self._team_request_removed()

    def test_a_rate_limited_request_removal_does_not_retry_the_task(self) -> None:
        # A retry would post the refusal again.
        self.github.get_collaborator_permission.return_value = "read"
        self.github.api_request.side_effect = GitHubRateLimitError("rate limited")

        _REQUEST.start(final_attempt=False)

        assert len(self._replies()) == 1

    @parameterized.expand([("retried_later", False), ("last_attempt", True)])
    def test_a_failed_permission_lookup_keeps_the_request_until_the_last_attempt(
        self, _name: str, final_attempt: bool
    ) -> None:
        self.github.get_collaborator_permission.side_effect = ConnectionError("github is down")

        with self.assertRaises(ConnectionError):
            _REQUEST.start(final_attempt=final_attempt)

        self.start.assert_not_called()
        assert self._team_request_removed() == final_attempt
        assert len(self._replies()) == (1 if final_attempt else 0)
