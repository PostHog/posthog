import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

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

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._resolve_posthog_user_from_event")
    def test_first_message_identifies_user_and_counts_one(self, mock_resolve, mock_capture):
        mock_resolve.return_value = self.user
        # A top-level mention has no thread_ts, so it is the first message in the session.
        event = {"type": "app_mention", "channel": "C001", "ts": "1700.0001", "user": "U123"}

        _report_slack_mention_received(event, self.integration, "T12345")

        assert mock_capture.call_count == 1
        kwargs = mock_capture.call_args.kwargs
        assert kwargs["distinct_id"] == "user-distinct-1"
        assert kwargs["event"] == "posthog code slack mention received"
        props = kwargs["properties"]
        assert props["is_first_message_in_session"] is True
        assert props["session_message_count"] == 1
        assert props["slack_session_id"] == "T12345:C001:1700.0001"
        assert props["slack_thread_ts"] == "1700.0001"
        assert props["slack_user_id"] == "U123"
        assert props["posthog_user_identified"] is True
        assert "$set" in props
        assert kwargs["groups"]["project"] == str(self.team.uuid)

    @patch("products.slack_app.backend.api.SlackIntegration")
    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._resolve_posthog_user_from_event")
    def test_followup_counts_thread_messages(self, mock_resolve, mock_capture, mock_slack_integration):
        mock_resolve.return_value = self.user
        mock_client = MagicMock()
        mock_client.conversations_replies.return_value = {"messages": [{}, {}, {}]}
        mock_slack_integration.return_value.client = mock_client
        # A reply in an existing thread carries a thread_ts distinct from its own ts.
        event = {
            "type": "app_mention",
            "channel": "C001",
            "ts": "1700.0009",
            "thread_ts": "1700.0001",
            "user": "U123",
        }

        _report_slack_mention_received(event, self.integration, "T12345")

        props = mock_capture.call_args.kwargs["properties"]
        assert props["is_first_message_in_session"] is False
        assert props["session_message_count"] == 3
        assert props["slack_session_id"] == "T12345:C001:1700.0001"
        mock_client.conversations_replies.assert_called_once_with(channel="C001", ts="1700.0001", limit=200)

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._resolve_posthog_user_from_event")
    def test_unresolved_user_falls_back_to_slack_distinct_id(self, mock_resolve, mock_capture):
        mock_resolve.return_value = None
        event = {"type": "app_mention", "channel": "C001", "ts": "1700.0001", "user": "U999"}

        _report_slack_mention_received(event, self.integration, "T12345")

        kwargs = mock_capture.call_args.kwargs
        assert kwargs["distinct_id"] == "slack:T12345:U999"
        assert kwargs["properties"]["posthog_user_identified"] is False
        assert "$set" not in kwargs["properties"]

    @patch("products.slack_app.backend.api.posthoganalytics.capture")
    @patch("products.slack_app.backend.api._resolve_posthog_user_from_event")
    def test_capture_failure_is_swallowed(self, mock_resolve, mock_capture):
        mock_resolve.side_effect = Exception("boom")
        event = {"type": "app_mention", "channel": "C001", "ts": "1700.0001", "user": "U123"}

        # Must not raise: analytics is best-effort and cannot break event handling.
        _report_slack_mention_received(event, self.integration, "T12345")

        assert mock_capture.call_count == 0
