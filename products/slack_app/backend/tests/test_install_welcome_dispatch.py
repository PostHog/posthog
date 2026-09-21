from unittest.mock import patch

from django.test import TestCase

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.inbox_channel import INBOX_ONBOARDING_REQUIRED_SCOPES
from products.slack_app.backend.onboarding import run_install_onboarding
from products.slack_app.backend.tasks import send_slack_install_welcome

WELCOME_ONLY_SCOPES = set(REQUIRED_SLACK_SCOPES) - set(INBOX_ONBOARDING_REQUIRED_SCOPES)
INBOX_SCOPES = set(REQUIRED_SLACK_SCOPES) | set(INBOX_ONBOARDING_REQUIRED_SCOPES)


class _InstallTestBase(TestCase):
    """One workspace's worth of rows, built once per class."""

    organization: Organization
    team: Team

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Install Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Install Team")


class TestInstallWelcomeDispatch(_InstallTestBase):
    """Which installs reach the welcome task, decided by the `Integration` post-save receiver."""

    def setUp(self):
        inbox_dispatch = patch("products.slack_app.backend.signals._start_inbox_onboarding_workflow", return_value=True)
        self.mock_inbox = inbox_dispatch.start()
        self.addCleanup(inbox_dispatch.stop)

    def _create(self, *, scopes: set[str], kind: str = "slack") -> Integration:
        with self.captureOnCommitCallbacks(execute=True):
            return Integration.objects.create(
                team=self.team,
                kind=kind,
                integration_id="T_INSTALL",
                config={"scope": ",".join(sorted(scopes)), "authed_user": {"id": "U_INSTALLER"}},
                sensitive_config={"access_token": "xoxb-test"},
            )

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_fresh_slack_install_dispatches_the_welcome(self, mock_delay):
        integration = self._create(scopes=WELCOME_ONLY_SCOPES)

        mock_delay.assert_called_once_with(integration_id=integration.id)

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_inbox_onboarding_owns_the_dm_when_it_will_run(self, mock_delay):
        self._create(scopes=INBOX_SCOPES)

        self.mock_inbox.assert_called_once()
        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_unreachable_inbox_onboarding_falls_back_to_the_welcome(self, mock_delay):
        # An enqueue that never lands would otherwise leave the installer with no greeting
        # at all, because the welcome already stood down for it.
        self.mock_inbox.return_value = False

        integration = self._create(scopes=INBOX_SCOPES)

        mock_delay.assert_called_once_with(integration_id=integration.id)

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_other_integration_kinds_are_left_alone(self, mock_delay):
        self._create(kind="github", scopes=set())

        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.send_slack_install_welcome.delay")
    def test_reauth_does_not_welcome_again(self, mock_delay):
        integration = self._create(scopes=WELCOME_ONLY_SCOPES)
        mock_delay.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            integration.save()

        mock_delay.assert_not_called()


class TestSendInstallWelcomeTask(_InstallTestBase):
    """What the task does once it reaches a worker."""

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_deleted_integration_is_a_no_op(self, mock_onboard):
        send_slack_install_welcome(integration_id=987654321)

        mock_onboard.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_non_slack_integration_is_a_no_op(self, mock_onboard):
        github = Integration.objects.create(team=self.team, kind="github", integration_id="G1")

        send_slack_install_welcome(integration_id=github.id)

        mock_onboard.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_slack_install_runs_the_same_onboarding_the_workflow_does(self, mock_onboard):
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_TASK", config={"authed_user": {"id": "U1"}}
        )

        send_slack_install_welcome(integration_id=integration.id)

        assert mock_onboard.call_args.args[0].id == integration.id


class TestInstallOnboardingWithoutChannelScopes(_InstallTestBase):
    """An install that cannot open the channel still gets onboarded, minus the channel work."""

    def setUp(self):
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_WELCOME",
            config={"scope": ",".join(sorted(WELCOME_ONLY_SCOPES)), "authed_user": {"id": "U_INSTALLER"}},
            sensitive_config={"access_token": "xoxb-test"},
        )

    @patch("products.slack_app.backend.onboarding.ensure_inbox_channel")
    @patch("products.slack_app.backend.onboarding.send_onboarding_dm")
    def test_dms_the_installer_without_touching_the_channel(self, mock_dm, mock_channel):
        run_install_onboarding(self.integration)

        mock_dm.assert_called_once_with(self.integration, "U_INSTALLER")
        mock_channel.assert_not_called()

    @patch("products.slack_app.backend.onboarding.send_onboarding_dm")
    def test_silent_without_an_authed_user(self, mock_dm):
        self.integration.config = {"scope": "chat:write"}

        run_install_onboarding(self.integration)

        mock_dm.assert_not_called()
