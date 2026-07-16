from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.tools.github_client import GitHubAPIError

_START = "products.review_hog.backend.api.reviews.start_review_pr_workflow"
_ACCESS = "products.review_hog.backend.api.reviews.GitHubIntegration.first_for_team_repository"
_META = "products.review_hog.backend.api.reviews._fetch_pr_metadata"


def _pr_meta(**overrides: object) -> MagicMock:
    meta = MagicMock()
    meta.is_fork = overrides.get("is_fork", False)
    meta.state = overrides.get("state", "open")
    meta.head_sha = overrides.get("head_sha", "abc123")
    return meta


class TestReviewHogUiTriggerApi(APIBaseTest):
    def _trigger(self, pr_url: str):
        return self.client.post(
            f"/api/projects/{self.team.id}/review_hog/reviews/trigger/", {"pr_url": pr_url}, format="json"
        )

    @patch(_META, return_value=_pr_meta())
    @patch(_ACCESS, return_value=object())
    @patch(_START, return_value="wf-ui-1")
    def test_trigger_starts_a_publishing_workflow_acting_as_the_requester(self, mock_start, mock_access, _mock_meta):
        # The URL is canonicalized (trailing /files dropped) and the requester is both the run user
        # and the acting user — losing the override would make the review follow the PR author's
        # perspectives instead of the person who asked for it.
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id):
            resp = self._trigger("https://github.com/PostHog/posthog.com/pull/123/files")

        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(resp.json(), {"workflow_id": "wf-ui-1", "status": "started"})
        mock_access.assert_called_once_with(self.team.id, "PostHog/posthog.com")
        mock_start.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog.com/pull/123",
            team_id=self.team.id,
            user_id=self.user.id,
            publish=True,
            acting_user_id=self.user.id,
            trigger_source="ui",
        )

    @parameterized.expand(
        [
            ("team_unset", None),
            ("other_team", 999_999),
        ]
    )
    @patch(_START)
    def test_rejected_unless_the_project_is_the_reviewhog_team(self, _name, team_setting, mock_start):
        with override_settings(REVIEWHOG_TEAM_ID=team_setting):
            resp = self._trigger("https://github.com/PostHog/posthog/pull/1")

        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @patch(_START)
    def test_non_pr_github_url_rejected(self, mock_start):
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id):
            resp = self._trigger("https://github.com/PostHog/posthog/issues/1")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()

    @patch(_ACCESS, return_value=None)
    @patch(_START)
    def test_inaccessible_repository_rejected_without_starting_a_workflow(self, mock_start, _mock_access):
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id):
            resp = self._trigger("https://github.com/other-org/private-repo/pull/5")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("can't access other-org/private-repo", resp.json()["error"])
        mock_start.assert_not_called()

    @parameterized.expand(
        [
            ("nonexistent", GitHubAPIError("not found", status=404), "No pull request #7"),
            ("fork", _pr_meta(is_fork=True), "fork"),
            ("closed", _pr_meta(state="closed"), "closed"),
        ]
    )
    @patch(_ACCESS, return_value=object())
    @patch(_START)
    def test_unreviewable_pr_rejected_synchronously(self, _name, meta_or_error, message, mock_start, _mock_access):
        # Without the sync PR fetch these die async in the fetch activity, before the report row
        # exists — the UI shows "started" and then nothing ever appears.
        side_effect = meta_or_error if isinstance(meta_or_error, Exception) else None
        return_value = None if side_effect else meta_or_error
        with (
            override_settings(REVIEWHOG_TEAM_ID=self.team.id),
            patch(_META, side_effect=side_effect, return_value=return_value),
        ):
            resp = self._trigger("https://github.com/PostHog/posthog.com/pull/7")

        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST, resp.content)
        self.assertIn(message, resp.json()["error"])
        mock_start.assert_not_called()

    @parameterized.expand(
        [
            # Published at the PR's current head: honesty response, no run. The row's lowercased
            # repository pins the cross-trigger casing match (__iexact) — other triggers store the
            # casing they were called with.
            ("already_reviewed_at_head", "abc123", status.HTTP_200_OK, "already_reviewed", False),
            ("head_advanced_since_publish", "older-sha", status.HTTP_202_ACCEPTED, "started", True),
        ]
    )
    @patch(_META, return_value=_pr_meta(head_sha="abc123"))
    @patch(_ACCESS, return_value=object())
    @patch(_START, return_value="wf-ui-2")
    def test_already_published_head_answers_honestly(
        self, _name, published_head_sha, expected_status, expected_marker, starts, mock_start, _mock_access, _mock_meta
    ):
        ReviewReport.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            repository="posthog/posthog.com",
            pr_number=123,
            pr_url="https://github.com/PostHog/posthog.com/pull/123",
            head_branch="feat-branch",
            base_branch="master",
            published_head_sha=published_head_sha,
        )
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id):
            resp = self._trigger("https://github.com/PostHog/posthog.com/pull/123")

        self.assertEqual(resp.status_code, expected_status, resp.content)
        self.assertEqual(resp.json()["status"], expected_marker)
        self.assertEqual(mock_start.called, starts)

    @parameterized.expand(
        [
            ("reviewhog_team", True),
            ("other_team", False),
        ]
    )
    def test_settings_expose_whether_reviews_can_be_triggered_here(self, _name, is_reviewhog_team):
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id if is_reviewhog_team else self.team.id + 1):
            resp = self.client.get(f"/api/projects/{self.team.id}/review_hog/settings/")

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["can_trigger_reviews"], is_reviewhog_team)
