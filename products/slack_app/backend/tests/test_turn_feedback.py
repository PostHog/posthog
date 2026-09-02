import json

from unittest.mock import patch

from django.apps import apps
from django.test import TestCase, override_settings

from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.services.slack_messages import TURN_FEEDBACK_ACTION_ID, turn_feedback_block
from products.slack_app.backend.services.turn_feedback import (
    _MODAL_TEXT_ACTION_ID,
    _MODAL_TEXT_BLOCK_ID,
    FEEDBACK_TEXT_MAX_LENGTH,
    TURN_FEEDBACK_MODAL_CALLBACK_ID,
)
from products.slack_app.backend.tests.helpers import sign_slack_request


@override_settings(DEBUG=True)
class TestTurnFeedback(TestCase):
    """A rating is only worth collecting if it lands on the run it was given about, so these
    drive the real thumbs the reply carries rather than a hand-written payload: producer and
    consumer sit in different modules and would otherwise drift apart unnoticed."""

    signing_secret = "posthog-code-test-secret"
    slack_team_id = "T12345"

    def setUp(self):
        self.client = APIClient()
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="member@example.com", distinct_id="user-member")
        self.integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id=self.slack_team_id, config={}
        )

        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        self.task = Task.objects.create(
            team=self.team,
            title="Fix the broken dashboard export",
            description="desc",
            origin_product=Task.OriginProduct.SLACK,
            created_by=self.user,
            repository="org/repo",
        )
        self.task_run = TaskRun.objects.create(task=self.task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        config = patch(
            "products.slack_app.backend.api.SlackIntegration.slack_config",
            return_value={"SLACK_APP_SIGNING_SECRET": self.signing_secret},
        )
        config.start()
        self.addCleanup(config.stop)
        slack = patch("products.slack_app.backend.services.turn_feedback.SlackIntegration")
        self.mock_slack = slack.start()
        self.addCleanup(slack.stop)
        analytics = patch("products.slack_app.backend.services.turn_feedback.posthoganalytics")
        self.mock_analytics = analytics.start()
        self.addCleanup(analytics.stop)
        bot_id = patch("products.slack_app.backend.services.turn_feedback.get_cached_bot_user_id", return_value="U_BOT")
        bot_id.start()
        self.addCleanup(bot_id.stop)

    def _post(self, payload: dict):
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), self.signing_secret)
        return self.client.post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    def _thumb_value(self, sentiment: str, run_id: str | None = None) -> str:
        element = turn_feedback_block(self.integration.id, run_id or str(self.task_run.id))["elements"][0]
        button = "positive_button" if sentiment == "positive" else "negative_button"
        return element[button]["value"]

    def test_the_modal_input_fits_slack_cap(self):
        # Slack caps a plain_text_input at 3000 and rejects the whole view past it, so the
        # modal never opens and a thumbs-down collects no reason. Raising this to match
        # another client's limit is the mistake this guards.
        assert FEEDBACK_TEXT_MAX_LENGTH <= 3000

    def _pick(self, value: str):
        return self._post(
            {
                "type": "block_actions",
                "team": {"id": self.slack_team_id},
                "user": {"id": "U_ALICE"},
                "channel": {"id": "C_SOURCE"},
                "message": {"ts": "222.1", "thread_ts": "111.1"},
                "trigger_id": "trigger-1",
                "actions": [
                    {"type": "button", "action_id": TURN_FEEDBACK_ACTION_ID, "value": value},
                ],
            }
        )

    @parameterized.expand([("positive", "good", False), ("negative", "bad", True)])
    def test_picking_a_rating_reports_it_against_the_run(self, sentiment, rating, asks_for_a_reason):
        response = self._pick(self._thumb_value(sentiment))

        assert response.status_code == 200
        self.mock_analytics.capture.assert_called_once()
        kwargs = self.mock_analytics.capture.call_args.kwargs
        assert kwargs["event"] == "$ai_metric"
        properties = kwargs["properties"]
        assert properties["$ai_metric_name"] == "quality"
        assert properties["$ai_metric_value"] == rating
        # Must match what the gateway stamps on the run's own generations, or a rating
        # cannot be joined to the turn it rates.
        assert properties["ai_product"] == "slack_app"
        assert properties["task_run_id"] == str(self.task_run.id)
        assert properties["task_id"] == str(self.task.id)
        # The rated answer's own message, so a thread of answers stays separable.
        assert properties["turn_id"] == "222.1"
        assert properties["feedback_source"] == "button"
        assert self.mock_slack.return_value.client.views_open.called is asks_for_a_reason

    def test_a_run_from_another_project_is_not_rated(self):
        other_org = Organization.objects.create(name="OtherOrg")
        other_team = Team.objects.create(organization=other_org, name="OtherTeam")
        Task = apps.get_model("tasks", "Task")
        TaskRun = apps.get_model("tasks", "TaskRun")
        other_task = Task.objects.create(
            team=other_team, title="Someone else's task", description="desc", repository="org/repo"
        )
        other_run = TaskRun.objects.create(task=other_task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        response = self._pick(self._thumb_value("negative", run_id=str(other_run.id)))

        assert response.status_code == 200
        self.mock_analytics.capture.assert_not_called()

    def _submit_reason(self, text: str):
        return self._post(
            {
                "type": "view_submission",
                "team": {"id": self.slack_team_id},
                "user": {"id": "U_ALICE"},
                "view": {
                    "callback_id": TURN_FEEDBACK_MODAL_CALLBACK_ID,
                    "private_metadata": json.dumps(
                        {
                            "integration_id": self.integration.id,
                            "run_id": str(self.task_run.id),
                            "turn_id": "222.1",
                        }
                    ),
                    "state": {"values": {_MODAL_TEXT_BLOCK_ID: {_MODAL_TEXT_ACTION_ID: {"value": text}}}},
                },
            }
        )

    def test_the_reason_is_reported_against_the_same_run(self):
        response = self._submit_reason("  it answered about the wrong dashboard  ")

        assert response.status_code == 200
        self.mock_analytics.capture.assert_called_once()
        kwargs = self.mock_analytics.capture.call_args.kwargs
        assert kwargs["event"] == "$ai_feedback"
        assert kwargs["properties"]["$ai_feedback_text"] == "it answered about the wrong dashboard"
        assert kwargs["properties"]["task_run_id"] == str(self.task_run.id)
        assert kwargs["properties"]["turn_id"] == "222.1"

    def test_an_empty_reason_keeps_the_modal_open(self):
        response = self._submit_reason("   ")

        assert response.json()["response_action"] == "errors"
        self.mock_analytics.capture.assert_not_called()

    def _react(self, reaction: str, item_user: str = "U_BOT"):
        body = json.dumps(
            {
                "type": "event_callback",
                "team_id": self.slack_team_id,
                "event_id": "Ev123",
                "event": {
                    "type": "reaction_added",
                    "user": "U_ALICE",
                    "reaction": reaction,
                    "item_user": item_user,
                    "item": {"type": "message", "channel": "C_SOURCE", "ts": "222.1"},
                },
            }
        ).encode()
        signed = sign_slack_request(body, self.signing_secret)
        return self.client.post(
            "/slack/event-callback/",
            data=body,
            content_type="application/json",
            HTTP_X_SLACK_SIGNATURE=signed.signature,
            HTTP_X_SLACK_REQUEST_TIMESTAMP=signed.timestamp,
        )

    def _reacted_message(self, blocks: list[dict]) -> None:
        self.mock_slack.return_value.client.conversations_replies.return_value = {
            "messages": [{"ts": "222.1", "blocks": blocks}]
        }

    @parameterized.expand(
        [
            ("+1", "good"),
            ("+1::skin-tone-3", "good"),
            ("thumbsup", "good"),
            ("-1", "bad"),
            ("-1::skin-tone-5", "bad"),
            ("thumbsdown", "bad"),
        ]
    )
    def test_a_thumb_reaction_reports_a_rating(self, reaction, rating):
        self._reacted_message([turn_feedback_block(self.integration.id, str(self.task_run.id))])

        response = self._react(reaction)

        assert response.status_code == 202
        self.mock_analytics.capture.assert_called_once()
        kwargs = self.mock_analytics.capture.call_args.kwargs
        assert kwargs["event"] == "$ai_metric"
        properties = kwargs["properties"]
        assert properties["$ai_metric_name"] == "quality"
        assert properties["$ai_metric_value"] == rating
        assert properties["feedback_source"] == "reaction"
        assert properties["reaction"] == reaction
        assert properties["task_run_id"] == str(self.task_run.id)
        assert properties["turn_id"] == "222.1"
        # A reaction carries no trigger_id, so a bad rating cannot be asked for a reason.
        assert not self.mock_slack.return_value.client.views_open.called

    def test_a_non_thumb_reaction_costs_no_slack_fetch(self):
        response = self._react("eyes")

        assert response.status_code == 202
        assert not self.mock_slack.return_value.client.conversations_replies.called
        self.mock_analytics.capture.assert_not_called()

    def test_a_thumb_on_a_human_message_costs_no_slack_fetch(self):
        response = self._react("+1", item_user="U_SOMEONE_ELSE")

        assert response.status_code == 202
        assert not self.mock_slack.return_value.client.conversations_replies.called
        self.mock_analytics.capture.assert_not_called()

    def test_a_thumb_on_a_bot_message_without_thumbs_is_not_a_rating(self):
        self._reacted_message([{"type": "section", "text": {"type": "mrkdwn", "text": "Working on it"}}])

        response = self._react("+1")

        assert response.status_code == 202
        self.mock_analytics.capture.assert_not_called()
