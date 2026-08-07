"""Region routing for ``app_home_opened``.

The ``zz_`` prefix keeps this file last in the package, and it has to stay: importing
``backend.api`` pulls in ``posthog.temporal``, whose import runs ``configure_logger`` and
installs Temporal's logger factory process-wide. Structlog binds loggers on first use, so
every module that logs after that point is stuck with the swapped factory and its
``caplog`` assertions go quiet — silently, since assertions that a log is *absent* still
pass. Sorting last means the log-asserting suites (``test_get_slack_email_for_user``,
``test_guess_repository``) have run before the swap. Same reasoning as
``test_zz_resolve_slack_user_with_link_no_access.py``.
"""

from unittest.mock import MagicMock, patch

from django.test import RequestFactory, TestCase

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team import Team

from products.slack_app.backend.api import (
    ROUTE_HANDLED_LOCALLY,
    ROUTE_PROXIED,
    route_posthog_code_event_to_relevant_region,
)
from products.slack_app.backend.services.slack_auth import write_auth_state_ok


class TestAppHomeOpenedRegionRouting(TestCase):
    SLACK_TEAM_ID = "T_HOME_ROUTING"

    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _create_local_integration(self) -> Integration:
        organization = Organization.objects.create(name="Home Org")
        team = Team.objects.create(organization=organization, name="Home Team")
        integration = Integration.objects.create(
            team=team,
            kind="slack",
            integration_id=self.SLACK_TEAM_ID,
            sensitive_config={"access_token": "xoxb-test"},
        )
        write_auth_state_ok(integration.id, bot_user_id=None)
        return integration

    def _route(self, host: str = "eu.posthog.com") -> str:
        request = self.factory.post("/slack/event-callback/", HTTP_HOST=host)
        return route_posthog_code_event_to_relevant_region(
            request, {"type": "app_home_opened", "user": "U001"}, self.SLACK_TEAM_ID
        )

    @patch("products.slack_app.backend.api.get_instance_region", return_value="EU")
    @patch("products.slack_app.backend.api._proxy_event_to_region", return_value=MagicMock())
    @patch("products.slack_app.backend.api._handle_app_home_opened")
    def test_forwards_to_other_region_when_workspace_is_not_local(
        self, mock_publish: MagicMock, mock_proxy: MagicMock, _region: MagicMock
    ) -> None:
        # Slack posts every event to one Request URL, so the receiving region may not hold the
        # integration row. Publishing locally here silently no-ops for the whole workspace.
        assert self._route() == ROUTE_PROXIED
        assert mock_proxy.called
        assert not mock_publish.called

    @patch("products.slack_app.backend.api.does_other_region_claim_workspace", return_value=False)
    @patch("products.slack_app.backend.api.get_instance_region", return_value="EU")
    @patch("products.slack_app.backend.api._proxy_event_to_region")
    @patch("products.slack_app.backend.api._handle_app_home_opened")
    def test_publishes_locally_when_workspace_is_local(
        self, mock_publish: MagicMock, mock_proxy: MagicMock, _region: MagicMock, _claims: MagicMock
    ) -> None:
        integration = self._create_local_integration()

        assert self._route() == ROUTE_HANDLED_LOCALLY
        assert not mock_proxy.called
        assert mock_publish.call_args.kwargs["integration"] == integration
