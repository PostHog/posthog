import json
import uuid
from typing import Any

from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.tests.helpers import sign_slack_request


class TestErrorTrackingInteractivity(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.signing_secret = "posthog-code-test-secret"
        self.organization = Organization.objects.create(name="ET Org")
        self.team = Team.objects.create(organization=self.organization, name="ET Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="dev-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T12345", sensitive_config={"access_token": "xoxb-test"}
        )
        self.issue_id = uuid.uuid4()

    def _payload(self, action_id: str, value: Any, *, slack_team_id: str = "T12345") -> dict:
        return {
            "type": "block_actions",
            "team": {"id": slack_team_id},
            "user": {"id": "U777"},
            "response_url": "https://hooks.slack.test/response",
            "actions": [{"action_id": action_id, "value": value}],
            "message": {"ts": "1234.9999", "blocks": []},
        }

    def _value(self, **overrides: Any) -> str:
        return json.dumps({"integration_id": self.integration.id, "issue_id": str(self.issue_id), **overrides})

    def _post(self, payload: dict) -> Any:
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    @parameterized.expand(
        [
            ("resolve", "error_tracking_issue_resolve", "resolve_issue_from_slack", "Resolved."),
            ("assign", "error_tracking_issue_assign_me", "assign_issue_to_user_from_slack", "Assigned to you."),
        ]
    )
    @patch("products.slack_app.backend.services.inbox_interactivity.requests.post")
    @patch("products.slack_app.backend.api._is_org_member")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_button_click_mutates_through_the_facade_and_acks_ephemerally(
        self, _name, action_id, facade_fn, expected_text, mock_config, mock_is_org_member, mock_post
    ):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_is_org_member.return_value = self.user

        with patch(f"products.error_tracking.backend.facade.issues.{facade_fn}", return_value="ok") as facade:
            response = self._post(self._payload(action_id, self._value()))

        assert response.status_code == 200
        facade.assert_called_once_with(self.issue_id, integration=self.integration, user=self.user)
        body = mock_post.call_args.kwargs["json"]
        assert body["response_type"] == "ephemeral"
        assert body["text"].startswith(expected_text)

    @patch("products.slack_app.backend.services.inbox_interactivity.requests.post")
    @patch("products.slack_app.backend.api._is_org_member")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_non_member_click_is_rejected_without_touching_the_issue(self, mock_config, mock_is_org_member, mock_post):
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_is_org_member.return_value = None

        with patch("products.error_tracking.backend.facade.issues.resolve_issue_from_slack") as facade:
            response = self._post(self._payload("error_tracking_issue_resolve", self._value()))

        assert response.status_code == 200
        facade.assert_not_called()
        assert "linked PostHog account" in mock_post.call_args.kwargs["json"]["text"]

    @patch("products.slack_app.backend.services.inbox_interactivity.requests.post")
    @patch("products.slack_app.backend.api._is_org_member")
    @patch("products.slack_app.backend.api.SlackIntegration.slack_config")
    def test_workspace_that_does_not_own_the_integration_is_ignored(self, mock_config, mock_is_org_member, mock_post):
        # The button names an integration, but the click comes from a different workspace.
        mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        mock_is_org_member.return_value = self.user

        with patch("products.error_tracking.backend.facade.issues.resolve_issue_from_slack") as facade:
            response = self._post(self._payload("error_tracking_issue_resolve", self._value(), slack_team_id="T999"))

        assert response.status_code == 200
        facade.assert_not_called()
        mock_post.assert_not_called()
