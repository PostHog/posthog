from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User

TRIGGER_URL = "/api/review_hog/trigger/"
_START = "products.review_hog.backend.api.trigger.start_review_pr_workflow"


@override_settings(REVIEWHOG_TRIGGER_TOKEN="secret-token", REVIEWHOG_TEAM_IDS=[99], REVIEWHOG_RUN_USER_ID=42)
class TestReviewHogTriggerApi(APIBaseTest):
    def setUp(self):
        super().setUp()
        # The class-level REVIEWHOG_TEAM_IDS=[99] / REVIEWHOG_RUN_USER_ID=42 must be a real team and an
        # active member of its org: the trigger rejects unauthorized run users (their sandbox
        # credentials 403 and the review hangs).
        self.trigger_team = Team.objects.create(id=99, organization=self.organization, name="reviewhog trigger")
        self.run_user = User.objects.create(id=42, email="run-user-42@posthog.com")
        OrganizationMembership.objects.create(organization=self.organization, user=self.run_user)

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

    @override_settings(REVIEWHOG_TEAM_IDS=[])
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
        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            resp = self.client.post(
                TRIGGER_URL,
                {"repo": "PostHog/posthog", "pr_number": 1},
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)

    @parameterized.expand(
        [
            ("membership_removed", False),
            ("still_member_but_disabled", True),
        ]
    )
    @override_settings(REVIEWHOG_RUN_USER_ID=None)
    @patch(_START, return_value="wf-1")
    def test_inactive_integration_creator_falls_back_to_active_org_member(self, _name, keep_membership, mock_start):
        departed = User.objects.create(email="departed@posthog.com", is_active=False)
        if keep_membership:
            OrganizationMembership.objects.create(organization=self.organization, user=departed)
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="inst-1",
            config={},
            sensitive_config={},
            created_by=departed,
        )
        with override_settings(REVIEWHOG_TEAM_IDS=[self.team.id]):
            resp = self.client.post(
                TRIGGER_URL,
                {"repo": "PostHog/posthog", "pr_number": 1},
                format="json",
                HTTP_AUTHORIZATION="Bearer secret-token",
            )
        self.assertEqual(resp.status_code, status.HTTP_202_ACCEPTED, resp.content)
        self.assertEqual(mock_start.call_args.kwargs["user_id"], self.user.id)

    @parameterized.expand(
        [
            ("deactivated", True),
            ("active_but_not_org_member", False),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_unauthorized_configured_run_user_rejected(self, _name, deactivate, mock_start):
        if deactivate:
            User.objects.filter(id=42).update(is_active=False)
        else:
            OrganizationMembership.objects.filter(user_id=42).delete()
        resp = self.client.post(
            TRIGGER_URL,
            {"repo": "PostHog/posthog", "pr_number": 1},
            format="json",
            HTTP_AUTHORIZATION="Bearer secret-token",
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        mock_start.assert_not_called()
