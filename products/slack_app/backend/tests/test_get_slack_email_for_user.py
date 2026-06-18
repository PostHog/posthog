import pytest
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.api import get_slack_email_for_user
from products.slack_app.backend.models import SlackUserProfileCache


@pytest.fixture
def integration(db):
    organization = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=organization, name="Test Team")
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T12345",
        sensitive_config={"access_token": "xoxb-test"},
    )


def _make_slack_response(payload):
    response = MagicMock()
    response.data = payload
    return response


def _slack_api_error(error_code):
    err = SlackApiError(message=f"slack returned {error_code}", response={"ok": False, "error": error_code})
    return err


class TestGetSlackEmailForUser:
    @patch("posthog.models.integration.WebClient")
    def test_returns_email_when_present_in_fresh_response(self, mock_webclient_class, integration):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = _make_slack_response(
            {"ok": True, "user": {"id": "U1", "profile": {"email": "dev@example.com"}}}
        )

        email = get_slack_email_for_user(integration, "U1")

        assert email == "dev@example.com"
        assert SlackUserProfileCache.objects.filter(integration=integration, slack_user_id="U1").exists()

    @patch("posthog.models.integration.WebClient")
    def test_logs_empty_response_when_users_info_returns_blank(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        # Both the cache-miss call inside ``get_slack_user_info`` and the explicit fresh
        # retry return an unusable response. ``normalize_slack_response`` collapses both
        # to ``{}``, so we should emit the dedicated empty-response log and bail.
        mock_client.users_info.return_value = _make_slack_response(None)

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        assert any("slack_app_resolve_user_email_empty_response" in record.message for record in caplog.records)

    @patch("posthog.models.integration.WebClient")
    def test_logs_missing_email_when_profile_has_no_email(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        # Bot token works but lacks ``users:read.email``, or the user's email is hidden:
        # Slack returns ``ok=true`` with a profile that has no ``email`` field.
        mock_client.users_info.return_value = _make_slack_response(
            {"ok": True, "user": {"id": "U1", "profile": {"display_name": "Dev"}}}
        )

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        assert any("slack_app_resolve_user_email_missing_in_profile" in record.message for record in caplog.records)

    @pytest.mark.parametrize(
        "error_code",
        [
            "token_revoked",
            "invalid_auth",
            "not_authed",
            "account_inactive",
            "token_expired",
        ],
    )
    @patch("posthog.models.integration.WebClient")
    def test_auth_error_marks_integration_errors(self, mock_webclient_class, integration, error_code, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error(error_code)

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        integration.refresh_from_db()
        assert integration.errors == ERROR_TOKEN_REFRESH_FAILED
        assert any("slack_app_resolve_user_email_failed" in record.message for record in caplog.records)
        assert any("slack_app_integration_token_marked_broken" in record.message for record in caplog.records)

    @patch("posthog.models.integration.WebClient")
    def test_non_auth_slack_error_does_not_mark_integration_errors(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error("user_not_found")

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        integration.refresh_from_db()
        assert integration.errors == ""
        assert any("slack_app_resolve_user_email_failed" in record.message for record in caplog.records)
        assert not any("slack_app_integration_token_marked_broken" in record.message for record in caplog.records)

    @patch("posthog.models.integration.WebClient")
    def test_auth_error_mark_is_idempotent(self, mock_webclient_class, integration):
        integration.errors = ERROR_TOKEN_REFRESH_FAILED
        integration.save(update_fields=["errors"])

        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error("token_revoked")

        with patch.object(Integration, "save") as save_spy:
            get_slack_email_for_user(integration, "U1")

        save_spy.assert_not_called()

    @patch("posthog.models.integration.WebClient")
    def test_generic_exception_logs_without_error_code(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = RuntimeError("boom")

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        integration.refresh_from_db()
        assert integration.errors == ""
        # The structured log records ``error_code=None`` for non-Slack exceptions so a
        # quick log filter still groups them with the auth-error rows.
        failed_records = [r for r in caplog.records if "slack_app_resolve_user_email_failed" in r.message]
        assert failed_records, "expected slack_app_resolve_user_email_failed to be logged"
