import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import _report_slack_mention_received


class TestReportSlackMentionReceived:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-distinct-1")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    @parameterized.expand(
        [
            # name, event, user_resolved, thread_reply_count, exp_first, exp_count, exp_identified
            (
                "first_message_resolved",
                {"channel": "C001", "ts": "1700.0001", "user": "U123"},
                True,
                None,
                True,
                1,
                True,
            ),
            (
                "thread_root_is_the_mention_itself",
                {"channel": "C001", "ts": "1700.0001", "thread_ts": "1700.0001", "user": "U123"},
                True,
                None,
                True,
                1,
                True,
            ),
            (
                "followup_counts_thread_messages",
                {"channel": "C001", "ts": "1700.0009", "thread_ts": "1700.0001", "user": "U123"},
                True,
                3,
                False,
                3,
                True,
            ),
            (
                "first_message_unresolved_user",
                {"channel": "C001", "ts": "1700.0001", "user": "U999"},
                False,
                None,
                True,
                1,
                False,
            ),
        ]
    )
    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api.resolve_posthog_user_from_event")
    def test_capture_properties(
        self,
        _name,
        event,
        user_resolved,
        thread_reply_count,
        exp_first,
        exp_count,
        exp_identified,
        mock_resolve,
        mock_capture,
        mock_slack_integration,
    ):
        mock_resolve.return_value = self.user if user_resolved else None
        if thread_reply_count is not None:
            mock_client = MagicMock()
            mock_client.conversations_replies.return_value = {"messages": [{}] * thread_reply_count}
            mock_slack_integration.return_value.client = mock_client

        _report_slack_mention_received(event, self.integration, "T12345")

        assert mock_capture.call_count == 1
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["event"] == "posthog code slack mention received"
        assert kwargs["send_feature_flags"] is True
        assert kwargs["groups"]["project"] == str(self.team.uuid)

        thread_ts = event.get("thread_ts") or event["ts"]
        expected_distinct_id = "user-distinct-1" if exp_identified else f"slack:T12345:{event['user']}"
        assert kwargs["distinct_id"] == expected_distinct_id

        props = kwargs["properties"]
        assert props["is_first_message_in_session"] is exp_first
        assert props["session_message_count"] == exp_count
        assert props["slack_session_id"] == f"T12345:{event['channel']}:{thread_ts}"
        assert props["slack_thread_ts"] == thread_ts
        assert props["slack_user_id"] == event["user"]
        assert props["posthog_user_identified"] is exp_identified
        assert ("$set" in props) is exp_identified

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api.resolve_posthog_user_from_event")
    def test_capture_failure_is_swallowed(self, mock_resolve, mock_capture):
        mock_resolve.side_effect = Exception("boom")
        event = {"channel": "C001", "ts": "1700.0001", "user": "U123"}

        # Must not raise: analytics is best-effort and cannot break Slack event handling.
        _report_slack_mention_received(event, self.integration, "T12345")

        assert mock_capture.call_count == 0
