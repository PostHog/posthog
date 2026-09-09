from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase

from parameterized import parameterized
from rest_framework import serializers, status

from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalUserAutonomyConfig
from products.signals.backend.slack_notification_targets import (
    is_slack_member_target,
    validate_slack_notification_target,
)


class TestSlackNotificationTargets(SimpleTestCase):
    @parameterized.expand(
        [
            ("member id", "U0123ABC456", True),
            ("member id with display name", "U0123ABC456|@sam", True),
            ("enterprise grid member", "W0123ABC456|@sam", True),
            ("public channel", "C0123ABC456|#alerts", False),
            ("private channel", "G0123ABC456|#alerts", False),
            # A `D` id is Slack's own DM conversation, delivered as a plain channel target.
            ("dm conversation", "D0123ABC456", False),
            ("free text", "not-a-target", False),
        ]
    )
    def test_is_slack_member_target(self, _name: str, target: str, expected: bool) -> None:
        assert is_slack_member_target(target) is expected

    def test_channel_target_is_not_resolved_against_slack(self) -> None:
        with patch("products.signals.backend.slack_notification_targets.SlackIntegration") as slack_cls:
            validate_slack_notification_target("C0123ABC456|#alerts", None)
        assert slack_cls.call_count == 0

    def test_member_target_without_a_workspace_is_rejected(self) -> None:
        with self.assertRaises(serializers.ValidationError):
            validate_slack_notification_target("U0123ABC456|@sam", None)


class TestSlackNotificationTargetAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T123",
            config={"team": {"id": "T123"}},
            sensitive_config={"access_token": "xoxb-test"},
            created_by=self.user,
        )

    def _url(self) -> str:
        return "/api/users/@me/signal_autonomy/"

    def _post(self, payload: dict, *, member: dict | None, email_member_id: str | None = None):
        """POST the payload with a Slack workspace that knows `member` and nobody else."""
        with patch("products.signals.backend.slack_notification_targets.SlackIntegration") as slack_cls:
            slack = slack_cls.return_value
            slack.get_user_by_id.side_effect = lambda member_id: (
                member if member and member_id == member["id"] else None
            )
            slack.client.users_lookupByEmail.return_value = {
                "ok": bool(email_member_id),
                "user": {"id": email_member_id},
            }
            response = self.client.post(
                self._url(), {"slack_notification_integration_id": self.integration.id, **payload}
            )
            return response, slack

    def _saved_target(self) -> str | None:
        config = SignalUserAutonomyConfig.objects.filter(user=self.user).first()
        return config.slack_notification_channel if config else None

    def test_direct_message_resolves_the_callers_own_slack_account_by_email(self):
        response, _ = self._post(
            {"slack_notification_direct_message": True},
            member={"id": "U0123ABC456", "profile": {"display_name": "sam"}},
            email_member_id="U0123ABC456",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._saved_target() == "U0123ABC456|@sam"

    def test_direct_message_prefers_the_slack_account_linked_to_posthog(self):
        # The linked account wins over an email match, which misses when the two emails differ.
        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.SLACK,
            integration_id="U0456DEF789",
            config={"slack_team_id": "T123"},
        )

        response, slack = self._post(
            {"slack_notification_direct_message": True},
            member={"id": "U0456DEF789", "profile": {"display_name": "kai"}},
            email_member_id="U0123ABC456",
        )

        assert response.status_code == status.HTTP_200_OK, response.json()
        assert self._saved_target() == "U0456DEF789|@kai"
        slack.client.users_lookupByEmail.assert_not_called()

    def test_direct_message_is_refused_when_the_workspace_has_no_account_for_the_caller(self):
        # Saving anyway would leave a setting that never delivers, which reads as "notifications on".
        response, _ = self._post({"slack_notification_direct_message": True}, member=None)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._saved_target() is None

    def test_member_target_the_workspace_cannot_dm_is_refused(self):
        # `get_user_by_id` refuses bots, deactivated accounts, guests, and outside members.
        response, _ = self._post({"slack_notification_channel": "U0123ABC456|@sam"}, member=None)

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert self._saved_target() is None
