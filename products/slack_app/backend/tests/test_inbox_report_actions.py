import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.constants import AvailableFeature
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.facade.api import claim_report_from_slack
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportSlackThread
from products.slack_app.backend.facade.api import slack_report_claim_button, slack_report_copy_prompt_button
from products.slack_app.backend.tests.helpers import sign_slack_request

REVIEW_BUTTON = {
    "type": "button",
    "text": {"type": "plain_text", "text": "Review in PostHog", "emoji": True},
    "url": "https://example.com/report",
}
SUMMARY_BLOCK = {"type": "section", "text": {"type": "mrkdwn", "text": "Checkout errors increased."}}


@override_settings(DEBUG=True)
@patch("products.slack_app.backend.services.inbox_report_actions.post_response_url")
@patch("products.slack_app.backend.api.SlackIntegration")
class TestInboxReportActionClick(TestCase):
    signing_secret = "posthog-code-test-secret"
    slack_team_id = "T12345"
    channel = "C001"
    message_ts = "1005.0000"

    def setUp(self) -> None:
        cache.clear()
        self.client = APIClient()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.member_user = User.objects.create(email="member@example.com", distinct_id="user-member")
        OrganizationMembership.objects.create(user=self.member_user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=self.slack_team_id,
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.READY, title="Fix checkout errors"
        )
        SignalReportSlackThread.objects.for_team(self.team.id).create(
            team=self.team,
            report=self.report,
            integration=self.integration,
            slack_workspace_id=self.slack_team_id,
            channel=self.channel,
            thread_ts=self.message_ts,
            kind=SignalReportSlackThread.Kind.INBOX_NOTIFICATION,
        )

    def _as_slack_user(self, email: str) -> Any:
        return patch(
            "products.slack_app.backend.api.get_slack_user_info",
            return_value={"user": {"profile": {"email": email}}},
        )

    def _click(self, mock_slack_cls: MagicMock, slack_user_id: str, action: dict[str, Any]) -> Any:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        block = {
            "type": "actions",
            "block_id": "report_actions",
            "elements": [
                slack_report_claim_button(self.integration.id),
                slack_report_copy_prompt_button(self.integration.id),
                REVIEW_BUTTON,
            ],
        }
        payload = {
            "type": "block_actions",
            "team": {"id": self.slack_team_id},
            "user": {"id": slack_user_id},
            "response_url": "https://example.com/slack-response",
            "container": {"type": "message", "channel_id": self.channel, "message_ts": self.message_ts},
            "message": {"ts": self.message_ts, "text": "Fix checkout errors", "blocks": [SUMMARY_BLOCK, block]},
            "actions": [{"action_id": action["action_id"], "block_id": block["block_id"], "value": action["value"]}],
        }
        body_str = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body_str.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body_str,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )

    def _claims_of(self, user: User) -> int:
        return SignalReportArtefact.objects.filter(
            team=self.team, report=self.report, type="work_claim", created_by=user
        ).count()

    def test_claim_click_assigns_the_report_and_names_the_person_on_the_message(
        self, mock_slack_cls: MagicMock, mock_response: MagicMock
    ) -> None:
        with self._as_slack_user(self.member_user.email):
            response = self._click(mock_slack_cls, "U_BOB", slack_report_claim_button(self.integration.id))

        assert response.status_code == 200
        assert self._claims_of(self.member_user) == 1
        body = mock_response.call_args.args[1]
        assert body["replace_original"] is True
        assert body["blocks"] == [
            SUMMARY_BLOCK,
            {"type": "context", "elements": [{"type": "mrkdwn", "text": "🙋 <@U_BOB> is on it"}]},
            {
                "type": "actions",
                "block_id": "report_actions",
                "elements": [slack_report_copy_prompt_button(self.integration.id), REVIEW_BUTTON],
            },
        ]

    @parameterized.expand(
        [
            ("not_a_project_member", "Only members of this PostHog project"),
            ("no_task_editor_access", "task editor access"),
            ("held_by_a_teammate", "Robin is already working on this report"),
        ]
    )
    def test_refused_claim_click_tells_only_the_person_and_claims_nothing(
        self, mock_slack_cls: MagicMock, mock_response: MagicMock, case: str, expected_note: str
    ) -> None:
        slack_email = self.member_user.email
        if case == "not_a_project_member":
            slack_email = "stranger@example.com"
        elif case == "no_task_editor_access":
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(resource="task", team=self.team, access_level="viewer")
        else:
            teammate = User.objects.create(email="robin@example.com", first_name="Robin", distinct_id="user-robin")
            assert claim_report_from_slack(self.team.id, str(self.report.id), user_id=teammate.id).status == "claimed"

        with self._as_slack_user(slack_email):
            response = self._click(mock_slack_cls, "U_BOB", slack_report_claim_button(self.integration.id))

        assert response.status_code == 200
        assert self._claims_of(self.member_user) == 0
        body = mock_response.call_args.args[1]
        assert body["response_type"] == "ephemeral"
        assert body["replace_original"] is False
        assert expected_note in body["text"]

    def test_copy_prompt_click_shows_the_prompt_only_to_the_person(
        self, mock_slack_cls: MagicMock, mock_response: MagicMock
    ) -> None:
        with self._as_slack_user(self.member_user.email):
            response = self._click(mock_slack_cls, "U_BOB", slack_report_copy_prompt_button(self.integration.id))

        assert response.status_code == 200
        assert self._claims_of(self.member_user) == 0
        body = mock_response.call_args.args[1]
        assert body["response_type"] == "ephemeral"
        assert body["replace_original"] is False
        prompt = body["blocks"][-1]["elements"][0]["elements"][0]["text"]
        assert f"/project/{self.team.id}/inbox/reports/{self.report.id} (report ID: {self.report.id})" in prompt
