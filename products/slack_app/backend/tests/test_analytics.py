import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.analytics import capture_slack_event


class TestCaptureSlackEvent:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-distinct-1")
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    @parameterized.expand(
        [
            # name, with_posthog_user, slack_user_id, expected_distinct_id, expected_identified
            ("resolved_user_wins", True, "U123", "user-distinct-1", True),
            ("slack_user_fallback", False, "U123", "slack:T12345:U123", False),
            ("team_fallback", False, None, None, False),  # expected_distinct_id filled in from team uuid
        ]
    )
    @patch("products.slack_app.backend.analytics.ph_background_capture")
    def test_distinct_id_ladder(
        self, _name, with_posthog_user, slack_user_id, expected_distinct_id, expected_identified, mock_background
    ):
        capture = MagicMock()
        mock_background.return_value = capture

        capture_slack_event(
            self.integration,
            "slack app test event",
            slack_user_id=slack_user_id,
            posthog_user=self.user if with_posthog_user else None,
            extra_prop="value",
        )

        kwargs = capture.call_args.kwargs
        assert kwargs["distinct_id"] == (expected_distinct_id or str(self.team.uuid))
        assert kwargs["event"] == "slack app test event"
        properties = kwargs["properties"]
        assert properties["posthog_user_identified"] is expected_identified
        assert properties["team_id"] == self.team.id
        assert properties["extra_prop"] == "value"
        assert ("$set" in properties) is with_posthog_user

    @patch("products.slack_app.backend.analytics.ph_background_capture", side_effect=RuntimeError("boom"))
    def test_capture_failure_is_swallowed(self, _mock_background):
        capture_slack_event(self.integration, "slack app test event")
