"""Access-denied branch of ``resolve_slack_user`` when a Slack user is linked
to a PostHog account that has no access to the workspace's project.

Lives in its own top-level test file (rather than next to the other linked-user
resolver tests in ``tests/services/test_slack_user_oauth.py``) so it sorts
alphabetically AFTER the caplog-driven tests in ``test_get_slack_email_for_user.py``
and ``test_guess_repository.py``. Earlier placement caused those tests' caplog
assertions to silently miss logs from ``products.slack_app.backend.api``: once
this test's data-setup signals emit through the structlog ``BoundLogger``, the
project-wide ``cache_logger_on_first_use=True`` config caches the logger before
caplog hooks in for the later tests, and they observe ``caplog.records == []``.

If a future caller reorders test files (e.g. via a new ``pytest-ordering`` plugin
or a forced random seed), the same caplog pollution may resurface — keep the
``zz_`` prefix.
"""

from unittest.mock import MagicMock, patch

from posthog.models.integration import SlackIntegration

from products.slack_app.backend.api import resolve_slack_user
from products.slack_app.backend.tests.conftest import SLACK_USER_ID


class TestResolveSlackUserAccessDenied:
    @patch("posthog.models.integration.WebClient")
    @patch("products.slack_app.backend.api.UserPermissions")
    @patch("products.slack_app.backend.api.is_slack_app_oauth_enabled")
    def test_flag_on_with_link_but_no_team_access_returns_none(
        self,
        mock_flag,
        mock_permissions_class,
        mock_webclient_class,
        org_team_user,
        workspace_integration,
        link_user,
    ):
        _, _, user = org_team_user
        link_user(user)
        mock_flag.return_value = True
        mock_client = MagicMock()
        mock_webclient_class.return_value = mock_client
        mock_permissions = MagicMock()
        mock_permissions.current_team.effective_membership_level = None
        mock_permissions_class.return_value = mock_permissions

        result = resolve_slack_user(
            SlackIntegration(workspace_integration), workspace_integration, SLACK_USER_ID, "C001", "1234.5"
        )
        assert result is None
        # User feedback is posted — access-denied message lands in Slack.
        assert mock_client.chat_postEphemeral.called or mock_client.chat_postMessage.called
