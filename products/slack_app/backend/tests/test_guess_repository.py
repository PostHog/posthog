import logging

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_repo_preference import UserRepoPreference

from products.slack_app.backend.api import (
    DefaultRepoCommand,
    _extract_explicit_repo,
    _get_full_repo_names,
    _parse_default_repo_command,
    select_repository,
)


@patch("products.slack_app.backend.api.GitHubIntegration")
class TestGetFullRepoNames:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    def test_no_github_integration_returns_empty(self, mock_github_class):
        result = _get_full_repo_names(self.slack_integration)
        assert result == []
        mock_github_class.assert_not_called()

    def test_single_integration_single_page(self, mock_github_class):
        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        mock_github = MagicMock()
        mock_github.organization.return_value = "posthog"
        mock_github.list_repositories.return_value = ["posthog", "posthog-js", "plugin-server"]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)
        assert result == ["posthog/plugin-server", "posthog/posthog", "posthog/posthog-js"]

    def test_pagination_across_pages(self, mock_github_class):
        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "org"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        page1 = [f"repo-{i}" for i in range(100)]
        page2 = [f"repo-{i}" for i in range(100, 120)]

        mock_github = MagicMock()
        mock_github.organization.return_value = "org"
        mock_github.list_repositories.side_effect = [page1, page2]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)
        assert len(result) == 120
        assert result == sorted(f"org/repo-{i}" for i in range(120))

    def test_multiple_integrations_aggregated(self, mock_github_class):
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="gh-1",
            config={"account": {"name": "orgA"}},
            sensitive_config={"access_token": "ghp-a"},
        )
        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="gh-2",
            config={"account": {"name": "orgB"}},
            sensitive_config={"access_token": "ghp-b"},
        )

        gh_a = MagicMock()
        gh_a.organization.return_value = "orgA"
        gh_a.list_repositories.return_value = ["repo-1"]

        gh_b = MagicMock()
        gh_b.organization.return_value = "orgB"
        gh_b.list_repositories.return_value = ["repo-2"]

        mock_github_class.side_effect = [gh_a, gh_b]

        result = _get_full_repo_names(self.slack_integration)
        assert result == ["orgA/repo-1", "orgB/repo-2"]

    @patch("products.slack_app.backend.api._MAX_GITHUB_REPOS", 5)
    def test_cap_reached_truncates_and_warns(self, mock_github_class, caplog):
        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "org"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        mock_github = MagicMock()
        mock_github.organization.return_value = "org"
        mock_github.list_repositories.return_value = [f"repo-{i}" for i in range(10)]
        mock_github_class.return_value = mock_github

        with caplog.at_level(logging.WARNING):
            result = _get_full_repo_names(self.slack_integration)

        assert len(result) == 5
        assert any("github_repo_list_capped" in r.message for r in caplog.records)

    def test_results_are_sorted(self, mock_github_class):
        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

        mock_github = MagicMock()
        mock_github.organization.return_value = "posthog"
        mock_github.list_repositories.return_value = ["zebra", "alpha", "middle"]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)
        assert result == ["posthog/alpha", "posthog/middle", "posthog/zebra"]


class TestExtractExplicitRepo:
    @parameterized.expand(
        [
            ("simple", "fix posthog/posthog-js please", "posthog/posthog-js"),
            ("no_match", "hello world", None),
            ("case_insensitive", "check PostHog/PostHog", "posthog/posthog"),
            ("url_false_positive", "see https://github.com/posthog/posthog/issues/1", None),
            ("backticks", "please fix `posthog/posthog-js`", "posthog/posthog-js"),
            (
                "slack_link_label",
                "use <https://github.com/posthog/posthog-js|posthog/posthog-js>",
                "posthog/posthog-js",
            ),
            ("multiple_first_wins", "check posthog/posthog-js then posthog/posthog", "posthog/posthog-js"),
            ("with_bot_mention", "<@U123> fix posthog/posthog-js", "posthog/posthog-js"),
        ]
    )
    def test_extract_explicit_repo(self, _name, text, expected):
        repos = ["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"]
        assert _extract_explicit_repo(text, repos) == expected


class TestSelectRepository:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-1")

        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

        self.thread_messages = [{"user": "Dev", "text": "please update readme"}]
        self.channel = "C001"

    def test_single_connected_repo_auto(self):
        decision = select_repository(
            event_text="please update readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog"
        assert decision.reason == "single_repo"
        assert decision.llm_called is False

    def test_explicit_repo_auto(self):
        decision = select_repository(
            event_text="fix posthog/posthog-js",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "explicit_mention"
        assert decision.llm_called is False

    def test_explicit_repo_with_bot_tag_noise_auto(self):
        decision = select_repository(
            event_text="<@U123> fix posthog/posthog-js",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "explicit_mention"
        assert decision.llm_called is False

    def test_no_explicit_multi_repo_prefers_picker(self):
        decision = select_repository(
            event_text="fix other/repo",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "picker"
        assert decision.repository is None
        assert decision.reason == "no_explicit_multi_repo"
        assert decision.llm_called is False

    def test_user_default_repo_auto(self):
        UserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
            scope_id=self.channel,
            repository="posthog/posthog-js",
        )

        decision = select_repository(
            event_text="add yolo to readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "user_default_repo"
        assert decision.llm_called is False

    def test_user_default_repo_is_channel_scoped(self):
        UserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
            scope_id="C_OTHER",
            repository="posthog/posthog-js",
        )

        decision = select_repository(
            event_text="add yolo to readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "picker"
        assert decision.reason == "no_explicit_multi_repo"

    def test_invalid_user_default_repo_is_cleared(self):
        UserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
            scope_id=self.channel,
            repository="posthog/deleted-repo",
        )

        decision = select_repository(
            event_text="add yolo to readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=["posthog/posthog", "posthog/posthog-js"],
        )

        assert decision.mode == "picker"
        assert decision.reason == "no_explicit_multi_repo"
        assert (
            UserRepoPreference.objects.filter(
                team=self.team,
                user=self.user,
                scope_type=UserRepoPreference.ScopeType.SLACK_CHANNEL,
                scope_id=self.channel,
            ).count()
            == 0
        )

    def test_no_repos_picker(self):
        decision = select_repository(
            event_text="add yolo to readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            user=self.user,
            channel=self.channel,
            all_repos=[],
        )

        assert decision.mode == "picker"
        assert decision.repository is None
        assert decision.reason == "no_repos"
        assert decision.llm_called is False


class TestParseDefaultRepoCommand:
    @parameterized.expand(
        [
            ("show", "default repo show", DefaultRepoCommand(action="show")),
            ("clear", "default repo clear", DefaultRepoCommand(action="clear")),
            ("set_bare", "default repo set", DefaultRepoCommand(action="set")),
            ("set_with_repo", "default repo set org/repo", DefaultRepoCommand(action="set", repository="org/repo")),
            ("case_insensitive", "Default Repo Show", DefaultRepoCommand(action="show")),
            ("extra_whitespace", "default  repo   show", DefaultRepoCommand(action="show")),
            ("bot_mention", "<@U123BOT> default repo clear", DefaultRepoCommand(action="clear")),
            (
                "dots_hyphens_in_repo",
                "default repo set my-org/my.repo-name",
                DefaultRepoCommand(action="set", repository="my-org/my.repo-name"),
            ),
        ]
    )
    def test_parses_command(self, _name, text, expected):
        assert _parse_default_repo_command(text) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("just_mention", "<@U123BOT>"),
            ("random_text", "fix the bug in posthog-js"),
            ("partial_command", "default repo"),
            ("unknown_action", "default repo delete"),
            ("repo_without_action", "default repo org/repo"),
        ]
    )
    def test_returns_none_for_non_commands(self, _name, text):
        assert _parse_default_repo_command(text) is None


class TestHandleDefaultRepoCommandActivity:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-1")

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack-twig",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

        self.channel = "C001"
        self.thread_ts = "1234567890.123456"
        self.slack_user_id = "U_SLACK"

    def _make_inputs(self, text: str):
        from posthog.temporal.ai.twig_slack_mention import TwigSlackMentionWorkflowInputs

        return TwigSlackMentionWorkflowInputs(
            event={"text": text, "channel": self.channel, "thread_ts": self.thread_ts, "user": self.slack_user_id},
            integration_id=self.integration.id,
            slack_team_id="T12345",
        )

    @patch("posthog.models.integration.SlackIntegration")
    def test_show_returns_current_default(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        UserRepoPreference.set_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            self.channel,
            repository="posthog/posthog",
        )

        from posthog.temporal.ai.twig_slack_mention import handle_twig_default_repo_command_activity

        result = handle_twig_default_repo_command_activity(
            self._make_inputs("<@U123> default repo show"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result is True
        mock_slack.client.chat_postMessage.assert_called_once()
        msg = mock_slack.client.chat_postMessage.call_args
        assert "posthog/posthog" in msg.kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_clear_returns_cleared_message(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        UserRepoPreference.set_default(
            self.team.id,
            self.user.id,
            UserRepoPreference.ScopeType.SLACK_CHANNEL,
            self.channel,
            repository="posthog/posthog",
        )

        from posthog.temporal.ai.twig_slack_mention import handle_twig_default_repo_command_activity

        result = handle_twig_default_repo_command_activity(
            self._make_inputs("<@U123> default repo clear"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result is True
        msg = mock_slack.client.chat_postMessage.call_args
        assert "Cleared" in msg.kwargs["text"]
        assert (
            UserRepoPreference.get_default(
                self.team.id, self.user.id, UserRepoPreference.ScopeType.SLACK_CHANNEL, self.channel
            )
            is None
        )

    @patch("products.slack_app.backend.api._post_repo_picker_message")
    @patch("products.slack_app.backend.api._get_full_repo_names", return_value=["posthog/posthog"])
    @patch("posthog.models.integration.SlackIntegration")
    def test_set_without_repo_posts_picker(self, mock_slack_cls, _mock_repos, mock_picker):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.twig_slack_mention import handle_twig_default_repo_command_activity

        result = handle_twig_default_repo_command_activity(
            self._make_inputs("<@U123> default repo set"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result is True
        mock_picker.assert_called_once()
