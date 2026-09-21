from unittest.mock import patch

from django.test import TestCase

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.inbox_channel import INBOX_ONBOARDING_REQUIRED_SCOPES
from products.slack_app.backend.onboarding import run_install_onboarding
from products.slack_app.backend.tasks import run_slack_install_onboarding

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


class TestInstallOnboardingDispatch(_InstallTestBase):
    """Which installs reach the onboarding, decided by the `Integration` post-save receiver."""

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

    @patch("products.slack_app.backend.tasks.run_slack_install_onboarding.delay")
    def test_a_fresh_install_runs_the_onboarding_workflow(self, mock_delay):
        self._create(scopes=INBOX_SCOPES)

        self.mock_inbox.assert_called_once()
        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_slack_install_onboarding.delay")
    def test_an_unreachable_workflow_falls_back_to_celery(self, mock_delay):
        # Without the fallback an enqueue that never lands leaves the installer with nothing.
        self.mock_inbox.return_value = False

        integration = self._create(scopes=INBOX_SCOPES)

        mock_delay.assert_called_once_with(integration_id=integration.id)

    @patch("products.slack_app.backend.tasks.run_slack_install_onboarding.delay")
    def test_an_install_without_the_channel_scope_is_left_alone(self, mock_delay):
        # The onboarding describes reporting into a channel it could not open for them.
        self._create(scopes=WELCOME_ONLY_SCOPES)

        self.mock_inbox.assert_not_called()
        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_slack_install_onboarding.delay")
    def test_other_integration_kinds_are_left_alone(self, mock_delay):
        self._create(kind="github", scopes=set())

        self.mock_inbox.assert_not_called()
        mock_delay.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_slack_install_onboarding.delay")
    def test_reauth_does_not_onboard_again(self, mock_delay):
        integration = self._create(scopes=INBOX_SCOPES)
        self.mock_inbox.reset_mock()

        with self.captureOnCommitCallbacks(execute=True):
            integration.save()

        self.mock_inbox.assert_not_called()
        mock_delay.assert_not_called()


class TestSendInstallWelcomeTask(_InstallTestBase):
    """What the task does once it reaches a worker."""

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_deleted_integration_is_a_no_op(self, mock_onboard):
        run_slack_install_onboarding(integration_id=987654321)

        mock_onboard.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_non_slack_integration_is_a_no_op(self, mock_onboard):
        github = Integration.objects.create(team=self.team, kind="github", integration_id="G1")

        run_slack_install_onboarding(integration_id=github.id)

        mock_onboard.assert_not_called()

    @patch("products.slack_app.backend.tasks.run_install_onboarding")
    def test_a_slack_install_runs_the_same_onboarding_the_workflow_does(self, mock_onboard):
        integration = Integration.objects.create(
            team=self.team, kind="slack", integration_id="T_TASK", config={"authed_user": {"id": "U1"}}
        )

        run_slack_install_onboarding(integration_id=integration.id)

        assert mock_onboard.call_args.args[0].id == integration.id


class TestRunInstallOnboarding(_InstallTestBase):
    """What the onboarding refuses to run for, once it reaches a worker."""

    def _integration(self, *, scopes: set[str], authed_user: bool = True) -> Integration:
        config: dict = {"scope": ",".join(sorted(scopes))}
        if authed_user:
            config["authed_user"] = {"id": "U_INSTALLER"}
        return Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_ONBOARD",
            config=config,
            sensitive_config={"access_token": "xoxb-test"},
        )

    @patch("products.slack_app.backend.onboarding.send_onboarding_dm")
    def test_silent_without_the_channel_scope(self, mock_dm):
        run_install_onboarding(self._integration(scopes=WELCOME_ONLY_SCOPES))

        mock_dm.assert_not_called()

    @patch("products.slack_app.backend.onboarding.send_onboarding_dm")
    def test_silent_without_an_authed_user(self, mock_dm):
        run_install_onboarding(self._integration(scopes=INBOX_SCOPES, authed_user=False))

        mock_dm.assert_not_called()
