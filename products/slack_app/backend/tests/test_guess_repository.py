import logging

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.repo_routing_rule import RepoRoutingRule
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.user_integration import UserIntegration

from products.slack_app.backend.api import (
    RulesCommand,
    _extract_explicit_repo,
    _get_full_repo_names,
    _invalidate_user_repo_list_cache,
    _parse_rules_command,
    _user_repo_list_cache_key,
)


def _repo_dict(org: str, name: str, repo_id: int = 1) -> dict:
    return {"id": repo_id, "name": name, "full_name": f"{org}/{name}"}


def _create_user_github_integration(
    user: User, *, integration_id: str = "gh-1", name: str = "posthog"
) -> UserIntegration:
    return UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=integration_id,
        config={"account": {"name": name}},
        sensitive_config={"access_token": "ghp-test"},
    )


@patch("products.slack_app.backend.api.UserGitHubIntegration")
class TestGetFullRepoNames:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="dev@example.com", distinct_id="user-1")

        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

    def test_no_user_github_integration_returns_empty(self, mock_github_class):
        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert result == []
        mock_github_class.assert_not_called()

    def test_single_integration_single_page(self, mock_github_class):
        _create_user_github_integration(self.user)

        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [
            _repo_dict("posthog", "posthog", 1),
            _repo_dict("posthog", "posthog-js", 2),
            _repo_dict("posthog", "plugin-server", 3),
        ]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert result == ["posthog/plugin-server", "posthog/posthog", "posthog/posthog-js"]

    def test_pagination_across_pages(self, mock_github_class):
        _create_user_github_integration(self.user, name="org")

        page1 = [_repo_dict("org", f"repo-{i}", i) for i in range(100)]
        page2 = [_repo_dict("org", f"repo-{i}", i) for i in range(100, 120)]

        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = page1 + page2
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert len(result) == 120
        assert result == sorted(f"org/repo-{i}" for i in range(120))

    def test_multiple_integrations_aggregated(self, mock_github_class):
        _create_user_github_integration(self.user, integration_id="gh-1", name="orgA")
        _create_user_github_integration(self.user, integration_id="gh-2", name="orgB")

        gh_a = MagicMock()
        gh_a.list_all_cached_repositories.return_value = [_repo_dict("orgA", "repo-1", 1)]

        gh_b = MagicMock()
        gh_b.list_all_cached_repositories.return_value = [_repo_dict("orgB", "repo-2", 2)]

        mock_github_class.side_effect = [gh_a, gh_b]

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert result == ["orgA/repo-1", "orgB/repo-2"]

    @patch("products.slack_app.backend.api._MAX_GITHUB_REPOS", 5)
    def test_cap_reached_truncates_and_warns(self, mock_github_class, caplog):
        _create_user_github_integration(self.user, name="org")

        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("org", f"repo-{i}", i) for i in range(10)]
        mock_github_class.return_value = mock_github

        with caplog.at_level(logging.WARNING):
            result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)

        assert len(result) == 5
        assert any("github_repo_list_capped" in r.message for r in caplog.records)

    def test_results_are_sorted(self, mock_github_class):
        _create_user_github_integration(self.user)

        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [
            _repo_dict("posthog", "zebra", 1),
            _repo_dict("posthog", "alpha", 2),
            _repo_dict("posthog", "middle", 3),
        ]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert result == ["posthog/alpha", "posthog/middle", "posthog/zebra"]


@patch("products.slack_app.backend.api.UserGitHubIntegration")
class TestGetFullRepoNamesCache:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Cache Org")
        self.team = Team.objects.create(organization=self.organization, name="Cache Team")
        self.user = User.objects.create(email="cache@example.com", distinct_id="user-cache")
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_CACHE",
            sensitive_config={"access_token": "xoxb-cache"},
        )

    def test_cache_miss_populates_cache(self, mock_github_class):
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)

        assert result == ["posthog/repo-a"]
        assert cache.get(_user_repo_list_cache_key(self.user.id)) == ["posthog/repo-a"]

    def test_cache_hit_avoids_github_api(self, mock_github_class):
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        mock_github_class.reset_mock()

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)

        assert result == ["posthog/repo-a"]
        mock_github_class.assert_not_called()

    def test_user_isolation(self, mock_github_class):
        user_b = User.objects.create(email="other@example.com", distinct_id="user-b")
        _create_user_github_integration(self.user, integration_id="gh-a", name="orgA")
        _create_user_github_integration(user_b, integration_id="gh-b", name="orgB")

        gh_a = MagicMock()
        gh_a.list_all_cached_repositories.return_value = [_repo_dict("orgA", "repo-a")]

        gh_b = MagicMock()
        gh_b.list_all_cached_repositories.return_value = [_repo_dict("orgB", "repo-b")]

        mock_github_class.side_effect = [gh_a, gh_b]

        result_a = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        result_b = _get_full_repo_names(self.slack_integration, user_id=user_b.id)

        assert result_a == ["orgA/repo-a"]
        assert result_b == ["orgB/repo-b"]

    def test_invalidation_forces_refetch(self, mock_github_class):
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        _invalidate_user_repo_list_cache(self.user.id)

        assert cache.get(_user_repo_list_cache_key(self.user.id)) is None

        mock_github.list_all_cached_repositories.return_value = [
            _repo_dict("posthog", "repo-a"),
            _repo_dict("posthog", "repo-b", 2),
        ]
        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert result == ["posthog/repo-a", "posthog/repo-b"]

    def test_no_github_integrations_caches_empty(self, mock_github_class):
        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)

        assert result == []
        assert cache.get(_user_repo_list_cache_key(self.user.id)) == []
        mock_github_class.assert_not_called()

    def test_empty_result_with_github_integrations_not_cached(self, mock_github_class):
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = []
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration, user_id=self.user.id)

        assert result == []
        assert cache.get(_user_repo_list_cache_key(self.user.id)) is None

    def test_signal_invalidates_on_user_github_save(self, mock_github_class):
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert cache.get(_user_repo_list_cache_key(self.user.id)) is not None

        UserIntegration.objects.create(
            user=self.user,
            kind=UserIntegration.IntegrationKind.GITHUB,
            integration_id="gh-new",
            config={"account": {"name": "new-org"}},
            sensitive_config={"access_token": "ghp-new"},
        )

        assert cache.get(_user_repo_list_cache_key(self.user.id)) is None

    def test_signal_invalidates_on_user_github_delete(self, mock_github_class):
        gh_record = _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert cache.get(_user_repo_list_cache_key(self.user.id)) is not None

        gh_record.delete()

        assert cache.get(_user_repo_list_cache_key(self.user.id)) is None

    def test_signal_isolated_to_user(self, mock_github_class):
        """A different user's GitHub install must not invalidate this user's cache."""
        other_user = User.objects.create(email="other-signal@example.com", distinct_id="user-other-signal")
        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration, user_id=self.user.id)
        assert cache.get(_user_repo_list_cache_key(self.user.id)) is not None

        _create_user_github_integration(other_user, integration_id="gh-other", name="other-org")

        assert cache.get(_user_repo_list_cache_key(self.user.id)) is not None


@patch("products.slack_app.backend.api.UserGitHubIntegration")
class TestPostRepoPickerPrewarm:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Prewarm Org")
        self.team = Team.objects.create(organization=self.organization, name="Prewarm Team")
        self.user = User.objects.create(email="prewarm@example.com", distinct_id="user-prewarm")
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T_PREWARM",
            sensitive_config={"access_token": "xoxb-prewarm"},
        )

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_prewarm_calls_get_full_repo_names(self, mock_slack_cls, mock_github_class):
        from products.slack_app.backend.api import _post_repo_picker_message

        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        _create_user_github_integration(self.user)
        mock_github = MagicMock()
        mock_github.list_all_cached_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _post_repo_picker_message(
            slack=mock_slack,
            integration=self.slack_integration,
            channel="C001",
            thread_ts="123.456",
            slack_user_id="U001",
            user_id=self.user.id,
            event_text="fix bug",
            user_message_ts=None,
            guidance="Pick a repo",
            action_id="posthog_code_repo_select",
        )

        assert cache.get(_user_repo_list_cache_key(self.user.id)) == ["posthog/repo-a"]


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


class TestParseRulesCommand:
    @parameterized.expand(
        [
            ("list", "rules list", RulesCommand(action="list")),
            ("case_insensitive", "Rules List", RulesCommand(action="list")),
            (
                "add",
                'rules add "JS SDK issues" org/js-sdk',
                RulesCommand(action="add", rule_text="JS SDK issues", repository="org/js-sdk"),
            ),
            (
                "add_with_dots",
                'rules add "fix frontend" my-org/my.repo',
                RulesCommand(action="add", rule_text="fix frontend", repository="my-org/my.repo"),
            ),
            ("remove", "rules remove 3", RulesCommand(action="remove", rule_numbers=[3])),
            ("remove_multiple", "rules remove 1,2", RulesCommand(action="remove", rule_numbers=[1, 2])),
            ("remove_multiple_spaces", "rules remove 1, 3", RulesCommand(action="remove", rule_numbers=[1, 3])),
            (
                "bot_mention_list",
                "<@U123BOT> rules list",
                RulesCommand(action="list"),
            ),
            (
                "add_no_repo",
                'rules add "JS SDK issues"',
                RulesCommand(action="add", rule_text="JS SDK issues"),
            ),
            (
                "bot_mention_add",
                '<@U123BOT> rules add "backend bugs" posthog/posthog',
                RulesCommand(action="add", rule_text="backend bugs", repository="posthog/posthog"),
            ),
            (
                "bot_mention_add_no_repo",
                '<@U123BOT> rules add "backend bugs"',
                RulesCommand(action="add", rule_text="backend bugs"),
            ),
            (
                "bot_mention_remove",
                "<@U123BOT> rules remove 1",
                RulesCommand(action="remove", rule_numbers=[1]),
            ),
            ("help", "help", RulesCommand(action="help")),
            ("help_case_insensitive", "Help", RulesCommand(action="help")),
            ("bot_mention_help", "<@U123BOT> help", RulesCommand(action="help")),
            (
                "deprecated_default_repo_set",
                "default repo set posthog/posthog",
                RulesCommand(action="deprecated_default_repo"),
            ),
            (
                "deprecated_default_repo_show",
                "default repo show",
                RulesCommand(action="deprecated_default_repo"),
            ),
            (
                "deprecated_default_repo_clear",
                "default repo clear",
                RulesCommand(action="deprecated_default_repo"),
            ),
            (
                "deprecated_default_repo_with_bot_mention",
                "<@U123BOT> default repo set posthog/posthog",
                RulesCommand(action="deprecated_default_repo"),
            ),
        ]
    )
    def test_parses_command(self, _name, text, expected):
        assert _parse_rules_command(text) == expected

    @parameterized.expand(
        [
            ("empty", ""),
            ("just_mention", "<@U123BOT>"),
            ("random_text", "fix the bug in posthog-js"),
            ("partial_command", "rules"),
            ("unknown_action", "rules delete"),
            ("add_no_quotes", "rules add JS issues org/repo"),
            ("remove_no_number", "rules remove"),
        ]
    )
    def test_returns_none_for_non_commands(self, _name, text):
        assert _parse_rules_command(text) is None


class TestHandleRulesCommandActivity:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create(email="test@example.com", distinct_id="user-1")

        self.integration = Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

        self.channel = "C001"
        self.thread_ts = "1234567890.123456"
        self.slack_user_id = "U_SLACK"

    def _make_inputs(self, text: str):
        from posthog.temporal.ai.slack_app import PostHogCodeSlackMentionWorkflowInputs

        return PostHogCodeSlackMentionWorkflowInputs(
            event={"text": text, "channel": self.channel, "thread_ts": self.thread_ts, "user": self.slack_user_id},
            integration_id=self.integration.id,
            slack_team_id="T12345",
        )

    @patch("posthog.models.integration.SlackIntegration")
    def test_list_empty_rules(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> rules list"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        msg = mock_slack.client.chat_postMessage.call_args
        assert "No routing rules" in msg.kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_help_uses_posthog_commands(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> help"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        msg = mock_slack.client.chat_postMessage.call_args
        assert "@PostHog <task description>" in msg.kwargs["text"]
        assert "@PostHog Code" not in msg.kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_list_shows_rules(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        RepoRoutingRule.objects.create(
            team=self.team, rule_text="JS SDK bugs", repository="posthog/posthog-js", priority=0
        )
        RepoRoutingRule.objects.create(
            team=self.team, rule_text="Backend issues", repository="posthog/posthog", priority=1
        )

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> rules list"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        msg = mock_slack.client.chat_postMessage.call_args
        assert "JS SDK bugs" in msg.kwargs["text"]
        assert "Backend issues" in msg.kwargs["text"]

    @patch(
        "products.slack_app.backend.api._get_full_repo_names", return_value=["posthog/posthog", "posthog/posthog-js"]
    )
    @patch("posthog.models.integration.SlackIntegration")
    def test_add_with_repo_creates_rule(self, mock_slack_cls, _mock_repos):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs('<@U123> rules add "JS SDK bugs" posthog/posthog-js'),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        rule = RepoRoutingRule.objects.get(team=self.team)
        assert rule.rule_text == "JS SDK bugs"
        assert rule.repository == "posthog/posthog-js"
        msg = mock_slack.client.chat_postMessage.call_args
        assert "Added rule" in msg.kwargs["text"]

    def test_add_without_repo_returns_needs_picker(self):
        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs('<@U123> rules add "JS SDK bugs"'),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "needs_picker"
        assert result.pending_rule_text == "JS SDK bugs"

    @patch("products.slack_app.backend.api._get_full_repo_names", return_value=["posthog/posthog"])
    @patch("posthog.models.integration.SlackIntegration")
    def test_add_rejects_disconnected_repo(self, mock_slack_cls, _mock_repos):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs('<@U123> rules add "JS bugs" posthog/nonexistent'),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        assert RepoRoutingRule.objects.filter(team=self.team).count() == 0
        msg = mock_slack.client.chat_postMessage.call_args
        assert "not connected" in msg.kwargs["text"]

    @patch("posthog.models.integration.SlackIntegration")
    def test_remove_deletes_rule(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        RepoRoutingRule.objects.create(team=self.team, rule_text="First rule", repository="org/repo", priority=0)
        RepoRoutingRule.objects.create(team=self.team, rule_text="Second rule", repository="org/repo2", priority=1)

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> rules remove 1"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        assert RepoRoutingRule.objects.filter(team=self.team).count() == 1
        remaining = RepoRoutingRule.objects.get(team=self.team)
        assert remaining.rule_text == "Second rule"

    @patch("posthog.models.integration.SlackIntegration")
    def test_remove_invalid_number(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        RepoRoutingRule.objects.create(team=self.team, rule_text="Only rule", repository="org/repo", priority=0)

        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> rules remove 5"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "handled"
        assert RepoRoutingRule.objects.filter(team=self.team).count() == 1
        msg = mock_slack.client.chat_postMessage.call_args
        assert "does not exist" in msg.kwargs["text"]

    def test_non_command_returns_not_a_command(self):
        from posthog.temporal.ai.slack_app import handle_posthog_code_rules_command_activity

        result = handle_posthog_code_rules_command_activity(
            self._make_inputs("<@U123> fix the bug in posthog-js"),
            self.channel,
            self.thread_ts,
            self.slack_user_id,
            self.user.id,
        )

        assert result.status == "not_a_command"


class TestRepoRoutingRuleModel:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.org = Organization.objects.create(name="Test Org")
        self.team_a = Team.objects.create(organization=self.org, name="Team A")
        self.team_b = Team.objects.create(organization=self.org, name="Team B")

    def test_ordering_by_priority_then_id(self):
        r2 = RepoRoutingRule.objects.create(team=self.team_a, rule_text="Second", repository="org/b", priority=1)
        r1 = RepoRoutingRule.objects.create(team=self.team_a, rule_text="First", repository="org/a", priority=0)

        rules = list(RepoRoutingRule.objects.filter(team=self.team_a))
        assert rules == [r1, r2]

    def test_team_scoping(self):
        RepoRoutingRule.objects.create(team=self.team_a, rule_text="Team A rule", repository="org/a", priority=0)
        RepoRoutingRule.objects.create(team=self.team_b, rule_text="Team B rule", repository="org/b", priority=0)

        team_a_rules = list(RepoRoutingRule.objects.filter(team=self.team_a))
        assert len(team_a_rules) == 1
        assert team_a_rules[0].rule_text == "Team A rule"
