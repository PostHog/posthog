import pytest
from unittest.mock import MagicMock, patch

from slack_sdk.errors import SlackApiError

from posthog.models.integration import Integration
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
    return SlackApiError(message=f"slack returned {error_code}", response={"ok": False, "error": error_code})


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
    def test_auth_error_logs_token_broken_flag(self, mock_webclient_class, integration, error_code, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error(error_code)

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        # No DB write — the integration row is untouched. Reconnect signal lives on the log line.
        integration.refresh_from_db()
        assert integration.errors == ""
        failed = [r for r in caplog.records if "slack_app_resolve_user_email_failed" in r.message]
        assert failed, "expected slack_app_resolve_user_email_failed to be logged"
        assert any(f"'error_code': '{error_code}'" in r.message for r in failed)
        assert any("'token_broken': True" in r.message for r in failed)

    @patch("posthog.models.integration.WebClient")
    def test_non_auth_slack_error_does_not_flag_token_broken(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error("user_not_found")

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        failed = [r for r in caplog.records if "slack_app_resolve_user_email_failed" in r.message]
        assert failed
        assert all("'token_broken': False" in r.message for r in failed)
        assert any("'error_code': 'user_not_found'" in r.message for r in failed)

    @patch("posthog.models.integration.WebClient")
    def test_generic_exception_logs_without_error_code(self, mock_webclient_class, integration, caplog):
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = RuntimeError("boom")

        with caplog.at_level("WARNING"):
            email = get_slack_email_for_user(integration, "U1")

        assert email is None
        failed = [r for r in caplog.records if "slack_app_resolve_user_email_failed" in r.message]
        assert failed
        # Non-Slack exceptions carry ``error_code=None`` and ``token_broken=False`` so a
        # log filter for "needs reconnect" cleanly excludes them.
        assert all("'error_code': None" in r.message for r in failed)
        assert all("'token_broken': False" in r.message for r in failed)


class TestAuthStateSideEffects:
    """The resolver pre-filter (``load_integrations``) consumes the cached
    verdict that these calls write. Success path → ``ok=true``; auth-class
    error → ``ok=false``; transient/non-auth error → no write so a Slack
    outage doesn't brick the workspace."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        from django.core.cache import cache

        cache.clear()
        yield
        cache.clear()

    @patch("posthog.models.integration.WebClient")
    def test_success_does_not_touch_auth_state(self, mock_webclient_class, integration):
        # The positive cache verdict is owned by the resolver's eager
        # ``auth.test`` layer. A successful ``users.info`` can hit the DB cache
        # (``SlackUserProfileCache``) without touching Slack at all, so it
        # proves nothing about the live token — letting it refresh the cache
        # would defeat the negative-cache mechanism the PR exists to provide.
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.return_value = _make_slack_response(
            {"ok": True, "user": {"id": "U1", "profile": {"email": "dev@example.com"}}}
        )

        get_slack_email_for_user(integration, "U1")

        assert get_cached_auth_state(integration.id) is None

    @pytest.mark.parametrize(
        "error_code",
        ["token_revoked", "invalid_auth", "not_authed", "account_inactive", "token_expired"],
    )
    @patch("posthog.models.integration.WebClient")
    def test_auth_class_error_writes_broken_state(self, mock_webclient_class, integration, error_code):
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error(error_code)

        get_slack_email_for_user(integration, "U1")

        state = get_cached_auth_state(integration.id)
        assert state is not None
        assert state.ok is False
        assert state.error_code == error_code

    @patch("posthog.models.integration.WebClient")
    def test_non_auth_slack_error_does_not_touch_cache(self, mock_webclient_class, integration):
        # ``user_not_found`` says nothing about token validity, so leaving the
        # cache untouched keeps the resolver from demoting a healthy install
        # based on an unrelated mention failing.
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = _slack_api_error("user_not_found")

        get_slack_email_for_user(integration, "U1")

        assert get_cached_auth_state(integration.id) is None

    @patch("posthog.models.integration.WebClient")
    def test_transient_exception_does_not_touch_cache(self, mock_webclient_class, integration):
        # Network blips and Slack 5xx must not brick the workspace by writing
        # a negative verdict for the full TTL.
        from products.slack_app.backend.services.slack_auth import get_cached_auth_state

        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_client.users_info.side_effect = RuntimeError("boom")

        get_slack_email_for_user(integration, "U1")

        assert get_cached_auth_state(integration.id) is None
