from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration

TRIGGER_URL = "/api/review_hog/trigger/"
_START = "products.review_hog.backend.api.trigger.start_review_pr_workflow"


@override_settings(REVIEWHOG_TRIGGER_TOKEN="secret-token", REVIEWHOG_TEAM_ID=99, REVIEWHOG_RUN_USER_ID=42)
class TestReviewHogTriggerApi(APIBaseTest):
    @patch(_START, return_value="wf-1")
    def test_valid_trigger_starts_workflow_and_publishes_by_default(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 123},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(resp.json(), {"workflow_id": "wf-1", "status": "started"})
        mock_start.assert_called_once_with(
            pr_url="https://github.com/PostHog/posthog/pull/123",
            team_id=99,
            user_id=42,
            publish=True,
            trigger_source="label",
        )

    @patch(_START, return_value="wf-1")
    def test_publish_flag_passes_through(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 5, "publish": False},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["publish"], False)

    @parameterized.expand(
        [
            ("wrong_token", "Bearer nope"),
            ("missing_header", ""),
            ("raw_wrong", "nope"),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_invalid_token_rejected(self, _name, auth_header, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION=auth_header,
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_disallowed_repo_rejected(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "evil/repo", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_allowlist_is_case_insensitive(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "posthog/posthog", "pr_number": 7},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        mock_start.assert_called_once()

    @override_settings(REVIEWHOG_TEAM_ID=None)
    @patch(_START, return_value="wf-1")
    def test_unconfigured_team_returns_503(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        mock_start.assert_not_called()

    @override_settings(DEBUG=False, TEST=False, REVIEWHOG_TRIGGER_TOKEN=None)
    @patch(_START, return_value="wf-1")
    def test_unconfigured_token_fails_closed_in_production(self, mock_start):
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer anything",
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)
        mock_start.assert_not_called()

    @override_settings(REVIEWHOG_RUN_USER_ID=None)
    @patch(_START, return_value="wf-1")
    def test_run_user_falls_back_to_integration_creator(self, mock_start):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="inst-1",
            config={},
            sensitive_config={},
            created_by=self.user,
        )
        with override_settings(REVIEWHOG_TEAM_ID=self.team.id):
            resp = self.client.post(
                TRIGGER_URL,
                {"repo": "PostHog/posthog", "pr_number": 1},
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)
