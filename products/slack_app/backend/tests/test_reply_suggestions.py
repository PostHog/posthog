import json
from typing import Any

from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.reply_suggestions import reply_suggestions_block, suggest_replies
from products.slack_app.backend.tests.helpers import sign_slack_request


def _completion(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestSuggestReplies(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "keeps_order_and_caps_count",
                json.dumps({"suggestions": ["Yes, open the PR", "Add tests too", "Use option 2", "No"]}),
                ["Yes, open the PR", "Add tests too", "Use option 2"],
            ),
            (
                # Slack rejects the whole message for one label over 75 characters.
                "drops_overlong_and_duplicate_labels",
                json.dumps({"suggestions": ["x" * 76, "Yes, open the PR", "Yes,  open the PR", ""]}),
                ["Yes, open the PR"],
            ),
            ("answer_asks_nothing", json.dumps({"suggestions": []}), []),
            ("prose_instead_of_json", "Sure, here are some ideas", []),
            ("wrong_shape", json.dumps({"suggestions": "Yes"}), []),
        ]
    )
    def test_suggestions_from_model_reply(self, _name: str, content: str, expected: list[str]) -> None:
        with patch("products.slack_app.backend.services.reply_suggestions.build_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.return_value = _completion(content)
            assert suggest_replies("Should I open a PR?") == expected

    def test_model_failure_offers_nothing(self) -> None:
        with patch("products.slack_app.backend.services.reply_suggestions.build_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()
            assert suggest_replies("Should I open a PR?") == []


@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
class TestReplySuggestionClick(TestCase):
    signing_secret = "posthog-code-test-secret"
    slack_team_id = "T12345"
    channel = "C001"
    thread_ts = "1000.0000"
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

    def _click(self, slack_user_id: str, index: int = 0) -> Any:
        block = reply_suggestions_block(self.integration.id, ["Yes, open the PR", "No, keep it local"])
        action = block["elements"][index]
        payload = {
            "type": "block_actions",
            "team": {"id": self.slack_team_id},
            "user": {"id": slack_user_id},
            "container": {
                "type": "message",
                "channel_id": self.channel,
                "message_ts": self.message_ts,
                "thread_ts": self.thread_ts,
            },
            "message": {"ts": self.message_ts, "thread_ts": self.thread_ts},
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

    def _as_slack_user(self, email: str) -> Any:
        return patch(
            "products.slack_app.backend.api.get_slack_user_info",
            return_value={"user": {"profile": {"email": email}}},
        )

    def test_click_sends_the_reply_to_the_agent_once(self, mock_slack_cls: MagicMock) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        with (
            self._as_slack_user(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            first = self._click("U_BOB", index=1)
            second = self._click("U_CAROL", index=0)

        assert first.status_code == second.status_code == 200
        mock_start.assert_called_once()
        assert mock_start.call_args.args[0] == {
            "type": "message",
            "user": "U_BOB",
            "channel": self.channel,
            "ts": self.message_ts,
            "thread_ts": self.thread_ts,
            "text": "No, keep it local",
        }
        # Without both, the click would face the classifier or start a new task in a thread with none.
        assert mock_start.call_args.kwargs["untagged_followup"] is True
        assert mock_start.call_args.kwargs["untagged_followup_confirmed"] is True
        update = mock_slack_cls.return_value.client.chat_update.call_args.kwargs
        assert update["ts"] == self.message_ts
        assert "actions" not in {block["type"] for block in update["blocks"]}

    def test_click_from_someone_outside_the_project_sends_nothing(self, mock_slack_cls: MagicMock) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}

        with (
            self._as_slack_user("stranger@example.com"),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click("U_STRANGER")

        assert response.status_code == 200
        mock_start.assert_not_called()
        mock_slack_cls.return_value.client.chat_update.assert_not_called()
