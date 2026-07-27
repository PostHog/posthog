"""Tests for the slash command webhook view.

The parser, dispatcher, and command workflow are covered by their own tests —
this file exercises the entry point's responsibilities: request validation,
retry handling, region routing, and handing a mention-shaped event plus the
``/posthog`` surface to the command workflow.
"""

from typing import Any
from urllib.parse import urlencode

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.test.client import RequestFactory

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.models import SlackUserProfileCache
from products.slack_app.backend.tests.helpers import sign_slack_request

SIGNING_SECRET = "posthog-code-test-secret"
SLASH_COMMAND_PATH = "/slack/command-callback/"


class _SlashCommandTestBase(TestCase):
    def setUp(self) -> None:
        cache.clear()
        self.client = APIClient()
        self.factory = RequestFactory()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")
        OrganizationMembership.objects.create(organization=self.organization, user=self.user)
        self.user.current_organization = self.organization
        self.user.current_team = self.team
        self.user.save()
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            config={"scope": ",".join(sorted(REQUIRED_SLACK_SCOPES))},
            sensitive_config={"access_token": "xoxb-posthog-code-test"},
        )

        from django.utils import timezone

        SlackUserProfileCache.objects.create(
            integration=self.integration,
            slack_user_id="U123",
            email="dev@example.com",
            display_name="Dev",
            real_name="Dev User",
            refreshed_at=timezone.now(),
        )

        # Every test in this file relies on the same signing-secret / SlackIntegration mocks;
        # lifting them into setUp via ``enterContext`` removes per-test decorator stacks and
        # keeps the test bodies focused on the slash-command behavior under exercise.
        self._mock_config = self.enterContext(
            patch("products.slack_app.backend.views.slack_command.SlackIntegration.slack_config")
        )
        self._mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": SIGNING_SECRET}

    def _post_slash_command(self, payload: dict[str, str]) -> Any:
        body = urlencode(payload).encode()
        signature, ts = sign_slack_request(body, SIGNING_SECRET)
        return self.client.post(
            SLASH_COMMAND_PATH,
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=ts,
        )

    def _default_payload(self, **overrides: str) -> dict[str, str]:
        payload = {
            "command": "/posthog",
            "team_id": "T12345",
            "user_id": "U123",
            "channel_id": "C001",
            "text": "",
            "response_url": "https://hooks.slack.example/abc",
            "trigger_id": "trig-1",
        }
        payload.update(overrides)
        return payload


class TestSlashCommandWebhookValidation(_SlashCommandTestBase):
    def test_method_not_allowed_on_get(self) -> None:
        response = self.client.get(SLASH_COMMAND_PATH)
        assert response.status_code == 405

    def test_rejects_bad_signature(self) -> None:
        self._mock_config.return_value = {"SLACK_APP_SIGNING_SECRET": "different-secret"}
        response = self._post_slash_command(self._default_payload(text="help"))
        assert response.status_code == 403

    def test_missing_required_payload_fields(self) -> None:
        response = self._post_slash_command(self._default_payload(team_id="", user_id=""))
        assert response.status_code == 200
        body = response.json()
        assert body["response_type"] == "ephemeral"
        assert "Missing Slack payload" in body["text"]


class TestSlashCommandDispatch(_SlashCommandTestBase):
    def setUp(self) -> None:
        super().setUp()
        # The entry point hands off to the durable command workflow (a Temporal
        # start — a genuine boundary), then acks Slack. Stub the start so tests
        # assert on the synthesised event and surface it forwards.
        self.mock_start = self.enterContext(
            patch("products.slack_app.backend.views.slack_command._start_command_workflow")
        )

    @parameterized.expand(
        [
            ("explicit_help", "help", "help"),
            # A bare ``/posthog`` (empty text) is treated as ``/posthog help``.
            ("bare_falls_back_to_help", "", "help"),
            ("rules_list", "rules list", "rules list"),
            ("project_set", "project 42", "project 42"),
        ]
    )
    def test_known_subcommand_starts_command_workflow(self, _name: str, text: str, expected_event_text: str) -> None:
        response = self._post_slash_command(self._default_payload(text=text))

        assert response.status_code == 200
        assert response.content == b""
        self.mock_start.assert_called_once()
        event = self.mock_start.call_args.args[0]
        # The workflow re-parses the text, so the entry point's job is to forward
        # a faithful mention-shaped event, not a parsed command.
        assert event["text"] == expected_event_text
        assert event["channel"] == "C001"
        assert event["user"] == "U123"
        # User resolution is deferred to the workflow to keep the ack under 3s.
        assert self.mock_start.call_args.kwargs["user_id"] is None
        # ``command_prefix`` is what surfaces in user-facing help/error copy — must
        # match the entry point so the strings tell users to type ``/posthog ...``.
        assert self.mock_start.call_args.kwargs["command_prefix"] == "/posthog"
        assert self.integration in self.mock_start.call_args.args[1]

    def test_unknown_sub_command_returns_help_text(self) -> None:
        response = self._post_slash_command(self._default_payload(text="frobnicate the widgets"))

        assert response.status_code == 200
        body = response.json()
        assert body["response_type"] == "ephemeral"
        assert "didn't recognize" in body["text"]
        self.mock_start.assert_not_called()

    def test_thread_ts_flows_through_to_workflow(self) -> None:
        """Slash commands invoked inside a thread carry ``thread_ts`` on the payload;
        passing it through keeps the bot's reply in-thread instead of dropping it at
        the bottom of the channel. Outside a thread the key is absent so the reply
        lands at the channel root."""
        in_thread = self._post_slash_command(self._default_payload(text="rules list", thread_ts="1700000000.001"))
        assert in_thread.status_code == 200
        assert self.mock_start.call_args.args[0]["thread_ts"] == "1700000000.001"

        self.mock_start.reset_mock()
        outside_thread = self._post_slash_command(self._default_payload(text="rules list"))
        assert outside_thread.status_code == 200
        assert "thread_ts" not in self.mock_start.call_args.args[0]


class TestSlashCommandWorkspaceMissing(_SlashCommandTestBase):
    def test_unknown_workspace_returns_not_connected_message(self) -> None:
        response = self._post_slash_command(self._default_payload(team_id="T_UNKNOWN", text="help"))
        assert response.status_code == 200
        body = response.json()
        assert body["response_type"] == "ephemeral"
        assert "isn't connected" in body["text"]
