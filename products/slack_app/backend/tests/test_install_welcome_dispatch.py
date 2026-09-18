from unittest.mock import patch

from django.test import TestCase

from parameterized import parameterized

from posthog.helpers.slack_scopes import REQUIRED_SLACK_SCOPES
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.slack_app.backend.inbox_channel import INBOX_ONBOARDING_REQUIRED_SCOPES
from products.slack_app.backend.services.slack_welcome_messages import send_install_welcome
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

    @parameterized.expand([("deleted_row", None), ("wrong_kind", "github")])
    @patch("products.slack_app.backend.tasks.send_install_welcome")
    def test_nothing_to_greet_is_a_no_op(self, _name, kind, mock_send):
        integration_id = 987654321
        if kind is not None:
            integration_id = Integration.objects.create(team=self.team, kind=kind, integration_id="G1").id

        send_slack_install_welcome(integration_id=integration_id)

        mock_send.assert_not_called()


class TestSendInstallWelcome(_InstallTestBase):
    """The DM itself: who gets it, and what it carries."""

    def setUp(self):
        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_WELCOME",
            config={"authed_user": {"id": "U_INSTALLER"}, "app_id": "A_WELCOME"},
            sensitive_config={"access_token": "xoxb-test"},
        )

    def _send(self, *, enabled: bool = True):
        module = "products.slack_app.backend.services.slack_welcome_messages"
        with (
            patch(f"{module}.is_slack_app_assistant_enabled", return_value=enabled),
            patch(f"{module}.SlackIntegration") as slack_cls,
        ):
            send_install_welcome(self.integration)
        return slack_cls.return_value.client.chat_postMessage

    def test_dms_the_installer(self):
        post = self._send()

        assert post.call_args.kwargs["channel"] == "U_INSTALLER"
        assert post.call_args.kwargs["text"]
        assert any(block.get("type") == "actions" for block in post.call_args.kwargs["blocks"])

    def test_silent_without_the_assistant_scopes(self):
        assert self._send(enabled=False).call_count == 0

    def test_silent_without_an_authed_user(self):
        self.integration.config = {}

        assert self._send().call_count == 0

    def test_a_slack_failure_does_not_raise(self):
        module = "products.slack_app.backend.services.slack_welcome_messages"
        with (
            patch(f"{module}.is_slack_app_assistant_enabled", return_value=True),
            patch(f"{module}.SlackIntegration") as slack_cls,
        ):
            slack_cls.return_value.client.chat_postMessage.side_effect = Exception("slack down")
            send_install_welcome(self.integration)
