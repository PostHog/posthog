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

from products.slack_app.backend.logic.reply_suggestions import (
    REPLY_SUGGESTIONS_BLOCK_ID,
    ReplySuggestionAttribution,
    SuggestedReply,
    clear_open_suggestions,
    remember_open_suggestions,
    reply_suggestions_block,
    suggest_replies,
)
from products.slack_app.backend.services.slack_messages import RunFooter
from products.slack_app.backend.slack_thread import SlackThreadContext, SlackThreadHandler
from products.slack_app.backend.tests.helpers import sign_slack_request

ANSWER_BLOCK = {"type": "markdown", "text": "Should I open a pull request?"}
FOOTER_BLOCK = {"type": "context", "elements": [{"type": "mrkdwn", "text": "Claude Opus 5"}]}
OPEN_PR = SuggestedReply(label="Yes, open the PR", reply="Yes, open the pull request with the fix")
KEEP_LOCAL = SuggestedReply(label="No, keep it local", reply="No, keep the change local for now")


def _suggestion(label: str, reply: str) -> dict[str, str]:
    return {"label": label, "reply": reply}


def _completion(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


class TestSuggestReplies(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "keeps_order_and_caps_count",
                json.dumps(
                    {
                        "suggestions": [
                            _suggestion(OPEN_PR.label, OPEN_PR.reply),
                            _suggestion(KEEP_LOCAL.label, KEEP_LOCAL.reply),
                            _suggestion("Add tests", "Add tests for the empty case too"),
                            _suggestion("Use option 2", "Use option 2"),
                        ]
                    }
                ),
                [OPEN_PR, KEEP_LOCAL, SuggestedReply(label="Add tests", reply="Add tests for the empty case too")],
            ),
            (
                # Slack rejects the whole message for one label over 75 characters.
                "drops_overlong_and_duplicate_labels",
                json.dumps(
                    {
                        "suggestions": [
                            _suggestion("x" * 76, "x"),
                            _suggestion(OPEN_PR.label, OPEN_PR.reply),
                            _suggestion("Yes,  open the PR", "Yes, open it"),
                            _suggestion("", "No label"),
                        ]
                    }
                ),
                [OPEN_PR],
            ),
            (
                "a_missing_reply_sends_the_label",
                json.dumps({"suggestions": [_suggestion("Use option 2", "")]}),
                [SuggestedReply(label="Use option 2", reply="Use option 2")],
            ),
            ("answer_asks_nothing", json.dumps({"suggestions": []}), []),
            ("prose_instead_of_json", "Sure, here are some ideas", []),
            ("wrong_shape", json.dumps({"suggestions": "Yes"}), []),
        ]
    )
    def test_suggestions_from_model_reply(self, _name: str, content: str, expected: list[SuggestedReply]) -> None:
        with patch("products.slack_app.backend.logic.reply_suggestions.build_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.return_value = _completion(content)
            assert suggest_replies("Should I open a PR?", ReplySuggestionAttribution()) == expected

    def test_generation_carries_what_online_evaluations_scope_and_join_on(self) -> None:
        attribution = ReplySuggestionAttribution(
            trace_id="trace-1", session_id="T1:C1:1.0", distinct_id="user-1", task_id="task-1", run_id="run-1"
        )
        with patch("products.slack_app.backend.logic.reply_suggestions.build_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.return_value = _completion(
                json.dumps({"suggestions": []})
            )
            suggest_replies("Should I open a PR?", attribution)

        assert build.call_args.kwargs == {
            "product": "slack_app_routing",
            "ai_product": "slack_app_routing",
            "trace_id": "trace-1",
            "session_id": "T1:C1:1.0",
            "distinct_id": "user-1",
            "properties": {"slack_app_classifier": "reply_suggestions", "task_id": "task-1", "run_id": "run-1"},
        }
        create = build.return_value.with_options.return_value.chat.completions.create
        assert create.call_args.kwargs["user"] == "user-1"

    def test_model_failure_offers_nothing(self) -> None:
        with patch("products.slack_app.backend.logic.reply_suggestions.build_openai_client") as build:
            build.return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()
            assert suggest_replies("Should I open a PR?", ReplySuggestionAttribution()) == []

    def test_the_person_message_reaches_the_model_apart_from_the_answer(self) -> None:
        with patch("products.slack_app.backend.logic.reply_suggestions.build_openai_client") as build:
            create = build.return_value.with_options.return_value.chat.completions.create
            create.return_value = _completion(json.dumps({"suggestions": []}))
            suggest_replies("Should I open a PR?", ReplySuggestionAttribution(), "Why does the retry never stop?")

        content = create.call_args.kwargs["messages"][1]["content"]
        assert content == (
            "<person_message>\nWhy does the retry never stop?\n</person_message>\n\n"
            "<agent_answer>\nShould I open a PR?\n</agent_answer>"
        )


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
        block = reply_suggestions_block(self.integration.id, [OPEN_PR, KEEP_LOCAL], "trace-1")
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
            "message": {
                "ts": self.message_ts,
                "thread_ts": self.thread_ts,
                "text": "Should I open a pull request?",
                "blocks": [ANSWER_BLOCK, block, FOOTER_BLOCK],
            },
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
        slack_client = mock_slack_cls.return_value.client
        slack_client.conversations_info.return_value = {"channel": {"is_ext_shared": False}}
        slack_client.chat_postMessage.return_value = {"ts": "1006.0000"}

        with (
            self._as_slack_user(self.member_user.email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
            patch("products.slack_app.backend.api.capture_slack_event") as mock_capture,
        ):
            first = self._click("U_BOB", index=1)
            second = self._click("U_CAROL", index=0)

        assert first.status_code == second.status_code == 200
        mock_start.assert_called_once()
        assert mock_start.call_args.args[0] == {
            "type": "message",
            "user": "U_BOB",
            "channel": self.channel,
            "ts": "1006.0000",
            "thread_ts": self.thread_ts,
            "text": KEEP_LOCAL.reply,
        }
        # Without both, the click would face the classifier or start a new task in a thread with none.
        assert mock_start.call_args.kwargs["untagged_followup"] is True
        assert mock_start.call_args.kwargs["untagged_followup_confirmed"] is True
        # The trace id joins the click to the generation that suggested it.
        mock_capture.assert_called_once()
        assert mock_capture.call_args.kwargs["ai_trace_id"] == "trace-1"
        # The reply is its own message in the thread, carrying the full text the label stood for.
        posted = slack_client.chat_postMessage.call_args.kwargs
        assert posted["thread_ts"] == self.thread_ts
        assert KEEP_LOCAL.reply in posted["text"]

    @parameterized.expand(
        [
            ("someone_outside_the_project", "stranger@example.com", False),
            # A typed reply here is dropped, so a click must not become the way around the approval.
            ("unapproved_slack_connect_channel", "member@example.com", True),
        ]
    )
    def test_click_that_must_not_reach_the_agent(
        self, mock_slack_cls: MagicMock, _name: str, email: str, ext_shared: bool
    ) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        slack_client = mock_slack_cls.return_value.client
        slack_client.conversations_info.return_value = {"channel": {"is_ext_shared": ext_shared}}

        with (
            self._as_slack_user(email),
            patch("products.slack_app.backend.api._start_mention_workflow") as mock_start,
        ):
            response = self._click("U_CLICKER")

        assert response.status_code == 200
        mock_start.assert_not_called()
        slack_client.chat_postMessage.assert_not_called()
        slack_client.chat_postEphemeral.assert_called_once()

    def test_a_failed_dispatch_leaves_the_buttons_usable(self, mock_slack_cls: MagicMock) -> None:
        mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": self.signing_secret}
        slack_client = mock_slack_cls.return_value.client
        slack_client.conversations_info.return_value = {"channel": {"is_ext_shared": False}}
        slack_client.chat_postMessage.return_value = {"ts": "1006.0000"}

        with (
            self._as_slack_user(self.member_user.email),
            patch(
                "products.slack_app.backend.api._start_mention_workflow", side_effect=[RuntimeError("temporal"), None]
            ) as mock_start,
        ):
            with self.assertRaises(RuntimeError):
                self._click("U_BOB")
            self._click("U_BOB")

        assert mock_start.call_count == 2
        # The reply that never reached the agent does not stay in the thread.
        slack_client.chat_delete.assert_called_once_with(channel=self.channel, ts="1006.0000")


class TestReplySuggestionPlacement(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @patch("products.slack_app.backend.slack_thread.capture_slack_event")
    @patch("products.slack_app.backend.slack_thread.suggest_replies", return_value=[OPEN_PR])
    @patch.object(SlackThreadHandler, "_actor_posthog_user", None)
    @patch.object(SlackThreadHandler, "_get_integration")
    @patch.object(SlackThreadHandler, "_get_client")
    def test_plain_answer_gets_the_buttons_under_its_text(
        self, mock_get_client, mock_get_integration, mock_suggest, _mock_capture
    ) -> None:
        mock_client = MagicMock()
        mock_client.chat_postMessage.return_value = {"ts": "2.0"}
        mock_get_client.return_value = mock_client
        mock_get_integration.return_value = Integration(id=7, config={}, integration_id="T1")
        handler = SlackThreadHandler(
            SlackThreadContext(integration_id=7, channel="C001", thread_ts="1.0"),
            RunFooter(model="claude-opus-5"),
            turn_person_message="why does the retry never stop?",
        )

        handler.post_thread_message("Should I open a pull request?", with_footer=True, markdown=True)
        handler.offer_reply_suggestions("Should I open a pull request?")

        posted = mock_client.chat_postMessage.call_args.kwargs["blocks"]
        mock_client.chat_postMessage.assert_called_once()
        update = mock_client.chat_update.call_args.kwargs
        assert update["ts"] == "2.0"
        assert update["blocks"][0] == posted[0]
        assert update["blocks"][1]["block_id"] == REPLY_SUGGESTIONS_BLOCK_ID
        assert update["blocks"][2:] == posted[1:]
        assert mock_suggest.call_args.args[2] == "why does the retry never stop?"


class TestClearOpenSuggestions(SimpleTestCase):
    def setUp(self) -> None:
        cache.clear()

    @parameterized.expand(
        [
            ("buttons_in_the_answer", [ANSWER_BLOCK, "buttons", FOOTER_BLOCK], [ANSWER_BLOCK, FOOTER_BLOCK]),
            ("buttons_alone", ["buttons"], None),
        ]
    )
    def test_a_newer_message_removes_only_the_buttons(self, _name: str, blocks: list, kept: list | None) -> None:
        buttons = reply_suggestions_block(7, [OPEN_PR], None)
        message = {"ts": "2.0", "text": "answer", "blocks": [buttons if b == "buttons" else b for b in blocks]}
        client = MagicMock()
        client.conversations_replies.return_value = {"messages": [message]}
        remember_open_suggestions(7, "C001", "1.0", "2.0")

        clear_open_suggestions(client, 7, "C001", "1.0")
        clear_open_suggestions(client, 7, "C001", "1.0")

        client.conversations_replies.assert_called_once()
        if kept is None:
            client.chat_delete.assert_called_once_with(channel="C001", ts="2.0")
            client.chat_update.assert_not_called()
        else:
            client.chat_update.assert_called_once_with(channel="C001", ts="2.0", text="answer", blocks=kept)
