import time
import contextlib

from unittest.mock import MagicMock, patch

from django.test import TestCase

from parameterized import parameterized

from posthog.models.github_integration_base import GitHubIntegrationError, ReauthorizationRequired
from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import NoAccessibleRepositories, UserIntegration

from products.slack_app.backend.temporal import (
    PostHogCodeSlackMentionWorkflowInputs,
    block_posthog_code_task_if_no_personal_github_activity,
)
from products.slack_app.backend.temporal.helpers import warn_if_personal_github_cannot_open_repository
from products.tasks.backend.facade.api import check_personal_github_repo_access
from products.tasks.backend.facade.contracts import PersonalGitHubRepoAccess

_GITHUB_APP_INSTALL_URL = "https://github.com/apps/posthog-test/installations/new"


def _make_inputs(
    integration_id: int, user_id: int, slack_team_id: str = "T_SLACK"
) -> PostHogCodeSlackMentionWorkflowInputs:
    return PostHogCodeSlackMentionWorkflowInputs(
        event={"channel": "C123", "ts": "1234.5678", "user": "U_ALICE", "text": "<@BOT> do something"},
        integration_id=integration_id,
        slack_team_id=slack_team_id,
        user_id=user_id,
    )


class TestBlockPostHogCodeTaskIfNoPersonalGitHub(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

    @patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration")
    def test_returns_true_and_posts_block_when_user_has_no_personal_github(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert kwargs["channel"] == "C123"
        assert kwargs["thread_ts"] == "1234.5678"
        assert "haven't connected" in kwargs["text"]

        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        button = action_block["elements"][0]
        assert button["text"]["text"] == "Connect GitHub"
        assert button["url"].endswith(f"/project/{self.team.id}/settings/user-personal-integrations")

    def _create_personal_github(self, *, usable: bool) -> None:
        sensitive_config: dict = {"user_access_token": "at", "user_refresh_token": "rt"}
        config: dict = {}
        if not usable:
            # Refresh token expired in the past — the row exists but can't mint a token.
            config["user_refresh_token_expires_at"] = 1
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="gh-1",
            config=config,
            sensitive_config=sensitive_config,
        )

    @patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration")
    def test_returns_false_and_posts_nothing_when_user_has_usable_personal_github(self, mock_slack_cls):
        self._create_personal_github(usable=True)
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is False
        mock_slack.client.chat_postMessage.assert_not_called()

    @patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration")
    def test_stale_personal_github_blocks_with_reconnect_wording(self, mock_slack_cls):
        self._create_personal_github(usable=False)
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        kwargs = mock_slack.client.chat_postMessage.call_args.kwargs
        assert "expired" in kwargs["text"]
        action_block = next(b for b in kwargs["blocks"] if b.get("type") == "actions")
        assert action_block["elements"][0]["text"]["text"] == "Reconnect GitHub"

    @patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration")
    def test_only_github_kind_counts_as_personal_integration(self, mock_slack_cls):
        UserIntegration.objects.create(
            user=self.user,
            kind="other-service",
            integration_id="x",
            config={},
            sensitive_config={},
        )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()

    @patch("products.slack_app.backend.temporal.activities.messaging.SlackIntegration")
    def test_another_users_github_integration_does_not_count(self, mock_slack_cls):
        other_user = User.objects.create(email="bob@test.com")
        UserIntegration.objects.create(
            user=other_user,
            kind="github",
            integration_id="gh-2",
            config={},
            sensitive_config={"access_token": "tok"},
        )
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        blocked = block_posthog_code_task_if_no_personal_github_activity(
            _make_inputs(self.integration.id, self.user.id), "C123", "1234.5678", self.user.id
        )

        assert blocked is True
        mock_slack.client.chat_postMessage.assert_called_once()


class TestWarnIfPersonalGitHubCannotOpenRepository(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="TestOrg")
        self.team = Team.objects.create(organization=self.org, name="TestTeam")
        self.user = User.objects.create(email="alice@test.com")

    @parameterized.expand(
        [
            # name, row config, user probe, installation probe, expected text, expected buttons
            ("no_connection", None, None, None, None, None),
            ("usable_with_access", {}, "example/project", True, None, None),
            ("github_outage", {}, "example/project", GitHubIntegrationError("boom", status_code=502), None, None),
            (
                "refresh_token_expired",
                {"user_refresh_token_expires_at": 1},
                None,
                None,
                "expired",
                ["Reconnect GitHub"],
            ),
            (
                "flagged_for_reauthorization",
                {"needs_reauthorization_at": 1767225600},
                None,
                None,
                "expired",
                ["Reconnect GitHub"],
            ),
            ("token_revoked_on_github", {}, ReauthorizationRequired("rejected"), None, "expired", ["Reconnect GitHub"]),
            (
                "user_cannot_see_repo",
                {},
                None,
                None,
                "can't access `example/project`",
                ["Manage repository access", "Check connection"],
            ),
            (
                "installation_excludes_repo",
                {},
                "example/project",
                False,
                "can't access `example/project`",
                ["Manage repository access", "Check connection"],
            ),
            (
                "token_revoked_after_cached_user_check",
                {},
                "example/project",
                ReauthorizationRequired("rejected"),
                "expired",
                ["Reconnect GitHub"],
            ),
            (
                "installation_has_no_repos_for_user",
                {},
                "example/project",
                NoAccessibleRepositories("none"),
                "can't access `example/project`",
                ["Manage repository access", "Check connection"],
            ),
        ]
    )
    def test_warns_only_when_an_existing_connection_cannot_open_the_repository(
        self, _name, row_config, user_probe, installation_probe, expected_text, expected_buttons
    ):
        if row_config is not None:
            UserIntegration.objects.create(
                user=self.user,
                kind="github",
                integration_id="gh-1",
                config=row_config,
                sensitive_config={"user_access_token": "at", "user_refresh_token": "rt"},
            )
        slack = MagicMock()

        def probe(result):
            return {"side_effect": result} if isinstance(result, Exception) else {"return_value": result}

        with (
            patch("posthog.models.user_integration.UserGitHubIntegration.resolve_user_repository", **probe(user_probe)),
            patch(
                "posthog.models.github_integration_base.GitHubIntegrationBase.installation_can_access_repository",
                **probe(installation_probe),
            ),
            patch(
                "posthog.api.github_callback.types.github_app_install_url_shareable",
                return_value=_GITHUB_APP_INSTALL_URL,
            ),
        ):
            warn_if_personal_github_cannot_open_repository(
                slack=slack,
                channel="C123",
                thread_ts="1234.5678",
                team_id=self.team.id,
                user_id=self.user.id,
                slack_user_id="U123",
                repository="example/project",
            )

        slack.client.chat_postMessage.assert_not_called()
        if expected_text is None:
            slack.client.chat_postEphemeral.assert_not_called()
            return

        kwargs = slack.client.chat_postEphemeral.call_args.kwargs
        assert kwargs["user"] == "U123"
        assert expected_text in kwargs["text"]
        buttons = next(b for b in kwargs["blocks"] if b.get("type") == "actions")["elements"]
        assert [b["text"]["text"] for b in buttons] == expected_buttons
        assert buttons[-1]["url"].endswith(f"/project/{self.team.id}/settings/user-personal-integrations")
        if "Manage repository access" in expected_buttons:
            assert buttons[0]["url"] == _GITHUB_APP_INSTALL_URL

    def test_skips_the_check_when_another_caller_holds_the_token_rotation_lock(self):
        UserIntegration.objects.create(
            user=self.user,
            kind="github",
            integration_id="gh-1",
            config={"user_access_token_expires_at": int(time.time()) - 60},
            sensitive_config={"user_access_token": "at", "user_refresh_token": "rt"},
        )

        @contextlib.contextmanager
        def lock_held_elsewhere(*_args, **_kwargs):
            yield False

        with (
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials._redis_lock",
                side_effect=lock_held_elsewhere,
            ),
            patch(
                "posthog.models.user_integration.UserGitHubIntegration.refresh_user_access_token",
                side_effect=AssertionError("refreshed the rotating token outside the lock"),
            ),
        ):
            access = check_personal_github_repo_access(self.user.id, "example/project")

        assert access == PersonalGitHubRepoAccess.OK
