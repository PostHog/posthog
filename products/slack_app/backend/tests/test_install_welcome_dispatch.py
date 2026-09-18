from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

# `channels:manage` is what hands the install to the inbox onboarding flow, which DMs the
# installer its own setup message.
INBOX_SCOPE = "channels:manage"


class TestInstallWelcomeDispatch(TestCase):
    """The install DM is dispatched from the `Integration` post-save receiver, so this
    covers which installs reach the task and which are left alone."""

    def setUp(self):
        self.organization = Organization.objects.create(name="Install Org")
        self.team = Team.objects.create(organization=self.organization, name="Install Team")
        # The sibling receiver on the same signal reaches Temporal for installs that hold
        # the inbox scopes; stub it so these tests never touch the network.
        inbox_dispatch = patch("products.slack_app.backend.signals._start_inbox_onboarding_workflow")
        inbox_dispatch.start()
        self.addCleanup(inbox_dispatch.stop)

    def _create(self, *, kind: str = "slack", scopes: set[str] | None = None) -> Integration:
        granted = scopes if scopes is not None else set(REQUIRED_SLACK_SCOPES)
        with self.captureOnCommitCallbacks(execute=True):
            return Integration.objects.create(
                team=self.team,
                kind=kind,
                integration_id="T_INSTALL",
                config={"scope": ",".join(sorted(granted)), "authed_user": {"id": "U_INSTALLER"}},
                sensitive_config={"access_token": "xoxb-test"},
            )

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_fresh_slack_install_dispatches_the_welcome(self, mock_delay):
        integration = self._create(scopes=set(REQUIRED_SLACK_SCOPES) - {INBOX_SCOPE})

        mock_delay.assert_called_once_with(integration_id=integration.id)

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_inbox_onboarding_owns_the_dm_when_it_will_run(self, mock_delay):
        self._create(scopes=set(REQUIRED_SLACK_SCOPES) | {INBOX_SCOPE})

        mock_delay.assert_not_called()

    @parameterized.expand([("github",), ("email",)])
    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_other_integration_kinds_are_left_alone(self, kind, mock_delay):
        self._create(kind=kind, scopes=set())

        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_reauth_does_not_welcome_again(self, mock_delay):
        integration = self._create(scopes=set(REQUIRED_SLACK_SCOPES) - {INBOX_SCOPE})
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            integration.save()

        mock_delay.assert_not_called()


class TestSendInstallWelcomeTask(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Task Org")
        self.team = Team.objects.create(organization=self.organization, name="Task Team")

    @patch("products.slack_app.backend.tasks.send_assistant_install_welcome")
    def test_missing_integration_is_a_no_op(self, mock_send):
        from products.slack_app.backend.tasks import send_slack_install_welcome

        send_slack_install_welcome(integration_id=987654321)

        mock_send.assert_not_called()

    @patch("products.slack_app.backend.tasks.send_assistant_install_welcome")
    def test_non_slack_integration_is_a_no_op(self, mock_send):
        from products.slack_app.backend.tasks import send_slack_install_welcome

        integration = Integration.objects.create(team=self.team, kind="github", integration_id="G1")

        send_slack_install_welcome(integration_id=integration.id)

        mock_send.assert_not_called()
