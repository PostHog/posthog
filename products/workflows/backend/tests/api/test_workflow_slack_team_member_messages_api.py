from datetime import timedelta
from typing import Any
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from parameterized import parameterized
from rest_framework import status
from slack_sdk.errors import SlackApiError

from posthog.jwt import PosthogJwtAudience, encode_jwt
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration
from posthog.redis import get_client
from posthog.test.authentication_checks import covers_authentication

from products.workflows.backend.presentation.views.workflow_slack_team_member_messages import (
    WorkflowSlackTeamMemberMessageJWTAuthentication,
)

SECRET = "test-workflow-slack-dm-team-member-jwt"
SLACK_WORKSPACE_ID = "T123"


def _slack_member(member_id: str, **overrides: object) -> dict:
    return {"user": {"id": member_id, "team_id": SLACK_WORKSPACE_ID, **overrides}}


def _slack_error(code: str) -> SlackApiError:
    return SlackApiError(code, MagicMock(get=lambda key, default=None: code))


@override_settings(WORKFLOW_SLACK_DM_TEAM_MEMBER_JWT_SECRETS=[SECRET])
class TestWorkflowSlackTeamMemberMessagesAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        get_client().flushall()
        self.client.logout()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id=SLACK_WORKSPACE_ID,
            sensitive_config={"access_token": "xoxb-test"},
        )
        self.member = User.objects.create_and_join(self.organization, "ada@example.com", None, first_name="Ada")

        self.slack_client = MagicMock()
        self.slack_client.users_info.side_effect = lambda user: _slack_member(user)
        self.slack_client.users_lookupByEmail.return_value = {"ok": True, "user": {"id": "U-by-email"}}
        client_patch = patch("posthog.models.integration.slack.WebClient", return_value=self.slack_client)
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _post(self, idempotency_key: str = "run-1:dm:0", **overrides: Any) -> Any:
        token = encode_jwt(
            {"team_id": self.team.id, "hog_flow_id": str(uuid4())},
            timedelta(minutes=5),
            PosthogJwtAudience.WORKFLOW_SLACK_DM_TEAM_MEMBER,
            signing_key=SECRET,
        )
        body = {
            "integration_id": self.integration.id,
            "recipient": "ada@example.com",
            "text": "Ticket needs you",
            "idempotency_key": idempotency_key,
            **overrides,
        }
        return self.client.post(
            f"/api/projects/{self.team.id}/workflow_slack_team_member_messages/",
            body,
            format="json",
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

    def _link_slack(self, slack_user_id: str, workspace_id: str = SLACK_WORKSPACE_ID) -> None:
        UserIntegration.objects.create(
            user=self.member,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id=slack_user_id,
            config={"slack_team_id": workspace_id},
        )

    @parameterized.expand(
        [
            ("linked_account_wins_over_email", SLACK_WORKSPACE_ID, "U-linked"),
            ("link_to_another_workspace_falls_back_to_email", "T-other", "U-by-email"),
        ]
    )
    @covers_authentication(WorkflowSlackTeamMemberMessageJWTAuthentication)
    def test_sends_dm_to_the_team_member(self, _name: str, linked_workspace: str, expected_member: str) -> None:
        self._link_slack("U-linked", workspace_id=linked_workspace)

        response = self._post(
            text="From <https://evil.example|Support> <!channel>",
            button_url="https://app.example.com/tickets/1",
            button_text="View ticket",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["outcome"], "sent")
        self.assertEqual(response.json()["slack_user_id"], expected_member)
        sent = self.slack_client.chat_postMessage.call_args.kwargs
        self.assertEqual(sent["channel"], expected_member)
        self.assertEqual(sent["text"], "From &lt;https://evil.example|Support&gt; &lt;!channel&gt;")
        button = sent["blocks"][1]["elements"][0]
        self.assertEqual((button["url"], button["text"]["text"]), ("https://app.example.com/tickets/1", "View ticket"))

    @parameterized.expand(
        [
            ("email_in_other_case", lambda member: "ADA@Example.com"),
            ("user_id", lambda member: str(member.id)),
            ("user_uuid", lambda member: str(member.uuid)),
        ]
    )
    def test_recipient_can_be_an_email_or_a_user_id(self, _name: str, recipient_for: Any) -> None:
        response = self._post(recipient=recipient_for(self.member))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.slack_client.users_lookupByEmail.assert_called_once_with(email="ada@example.com")

    def test_blank_recipient_skips_the_step(self) -> None:
        response = self._post(recipient="  ")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["outcome"], "skipped")
        self.slack_client.chat_postMessage.assert_not_called()

    def test_retry_of_the_same_step_does_not_send_twice(self) -> None:
        first = self._post()
        retry = self._post()
        next_step = self._post(idempotency_key="run-1:dm:1")

        self.assertEqual([first.status_code, retry.status_code, next_step.status_code], [200, 200, 200])
        self.assertEqual(retry.json()["slack_user_id"], "U-by-email")
        self.assertEqual(self.slack_client.chat_postMessage.call_count, 2)

    @parameterized.expand(
        [
            ("slack_refused_so_retry_sends", _slack_error("channel_not_found"), "channel_not_found", 2),
            ("outcome_unknown_so_retry_replays", TimeoutError("read timed out"), "did not confirm", 1),
        ]
    )
    def test_failed_send_then_retry(
        self, _name: str, send_error: Exception, expected_error: str, expected_sends: int
    ) -> None:
        self.slack_client.chat_postMessage.side_effect = [send_error, {"ok": True}]

        failed = self._post()
        retried = self._post()

        self.assertEqual(failed.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(expected_error, failed.json()["detail"])
        self.assertEqual(retried.status_code, status.HTTP_200_OK)
        self.assertEqual(self.slack_client.chat_postMessage.call_count, expected_sends)

    def _member_of_another_organization(self) -> str:
        other = Organization.objects.create(name="Other")
        User.objects.create_and_join(other, "outsider@example.com", None)
        return "outsider@example.com"

    def _member_who_left(self) -> str:
        OrganizationMembership.objects.filter(user=self.member).delete()
        return "ada@example.com"

    def _deactivated_member(self) -> str:
        self.member.is_active = False
        self.member.save(update_fields=["is_active"])
        return "ada@example.com"

    def _member_not_in_slack(self) -> str:
        self.slack_client.users_lookupByEmail.side_effect = _slack_error("users_not_found")
        return "ada@example.com"

    def _member_matching(self, **overrides: object) -> str:
        self.slack_client.users_info.side_effect = lambda user: _slack_member(user, **overrides)
        return "ada@example.com"

    @parameterized.expand(
        [
            ("member_of_another_organization", _member_of_another_organization, "not a member of this project"),
            ("member_who_left", _member_who_left, "not a member of this project"),
            ("deactivated_member", _deactivated_member, "not a member of this project"),
            ("not_an_email_or_id", lambda t: "Ada Lovelace", "not an email address or a PostHog user ID"),
            ("no_slack_member_for_email", _member_not_in_slack, "could not find Ada"),
            ("email_matches_slack_connect_member", lambda t: t._member_matching(team_id="T-x"), "could not find Ada"),
            ("email_matches_guest", lambda t: t._member_matching(is_restricted=True), "could not find Ada"),
        ]
    )
    def test_undeliverable_recipient_fails_the_step(self, _name: str, arrange: Any, expected_error: str) -> None:
        response = self._post(recipient=arrange(self))

        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn(expected_error, response.json()["detail"])
        self.slack_client.chat_postMessage.assert_not_called()

    def test_slack_integration_from_another_team_is_refused(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        foreign = Integration.objects.create(
            team=other_team, kind="slack", integration_id="T999", sensitive_config={"access_token": "xoxb-other"}
        )

        response = self._post(integration_id=foreign.id)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.slack_client.chat_postMessage.assert_not_called()

    def test_button_link_must_be_http(self) -> None:
        response = self._post(button_url="javascript:alert(1)")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.slack_client.chat_postMessage.assert_not_called()
