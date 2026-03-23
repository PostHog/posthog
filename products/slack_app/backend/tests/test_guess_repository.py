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
from posthog.models.user_repo_preference import UserRepoPreference

from products.slack_app.backend.api import (
    RulesCommand,
    _extract_explicit_repo,
    _get_full_repo_names,
    _invalidate_repo_list_cache,
    _match_repo_rule,
    _parse_rules_command,
    _repo_list_cache_key,
    select_repository,
)


def _repo_dict(org: str, name: str, repo_id: int = 1) -> dict:
    return {"id": repo_id, "name": name, "full_name": f"{org}/{name}"}


@patch("products.slack_app.backend.api.GitHubIntegration")
class TestGetFullRepoNames:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
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
        mock_github.list_repositories.return_value = [
            _repo_dict("posthog", "posthog", 1),
            _repo_dict("posthog", "posthog-js", 2),
            _repo_dict("posthog", "plugin-server", 3),
        ]
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

        page1 = [_repo_dict("org", f"repo-{i}", i) for i in range(100)]
        page2 = [_repo_dict("org", f"repo-{i}", i) for i in range(100, 120)]

        mock_github = MagicMock()
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
        gh_a.list_repositories.return_value = [_repo_dict("orgA", "repo-1", 1)]

        gh_b = MagicMock()
        gh_b.list_repositories.return_value = [_repo_dict("orgB", "repo-2", 2)]

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
        mock_github.list_repositories.return_value = [_repo_dict("org", f"repo-{i}", i) for i in range(10)]
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
        mock_github.list_repositories.return_value = [
            _repo_dict("posthog", "zebra", 1),
            _repo_dict("posthog", "alpha", 2),
            _repo_dict("posthog", "middle", 3),
        ]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)
        assert result == ["posthog/alpha", "posthog/middle", "posthog/zebra"]


@patch("products.slack_app.backend.api.GitHubIntegration")
class TestGetFullRepoNamesCache:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Cache Org")
        self.team = Team.objects.create(organization=self.organization, name="Cache Team")
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T_CACHE",
            sensitive_config={"access_token": "xoxb-cache"},
        )

    def _create_github_integration(self, team=None, name="posthog"):
        return Integration.objects.create(
            team=team or self.team,
            kind="github",
            config={"account": {"name": name}},
            sensitive_config={"access_token": "ghp-test"},
        )

    def test_cache_miss_populates_cache(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)

        assert result == ["posthog/repo-a"]
        assert cache.get(_repo_list_cache_key(self.team.id)) == ["posthog/repo-a"]

    def test_cache_hit_avoids_github_api(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration)
        mock_github_class.reset_mock()

        result = _get_full_repo_names(self.slack_integration)

        assert result == ["posthog/repo-a"]
        mock_github_class.assert_not_called()

    def test_team_isolation(self, mock_github_class):
        org_b = Organization.objects.create(name="Other Org")
        team_b = Team.objects.create(organization=org_b, name="Other Team")
        slack_b = Integration.objects.create(
            team=team_b,
            kind="slack-posthog-code",
            integration_id="T_OTHER",
            sensitive_config={"access_token": "xoxb-other"},
        )
        self._create_github_integration(team=self.team, name="orgA")
        self._create_github_integration(team=team_b, name="orgB")

        gh_a = MagicMock()
        gh_a.list_repositories.return_value = [_repo_dict("orgA", "repo-a")]

        gh_b = MagicMock()
        gh_b.list_repositories.return_value = [_repo_dict("orgB", "repo-b")]

        mock_github_class.side_effect = [gh_a, gh_b]

        result_a = _get_full_repo_names(self.slack_integration)
        result_b = _get_full_repo_names(slack_b)

        assert result_a == ["orgA/repo-a"]
        assert result_b == ["orgB/repo-b"]

    def test_invalidation_forces_refetch(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration)
        _invalidate_repo_list_cache(self.team.id)

        assert cache.get(_repo_list_cache_key(self.team.id)) is None

        mock_github.list_repositories.return_value = [
            _repo_dict("posthog", "repo-a"),
            _repo_dict("posthog", "repo-b", 2),
        ]
        result = _get_full_repo_names(self.slack_integration)
        assert result == ["posthog/repo-a", "posthog/repo-b"]

    def test_no_github_integrations_caches_empty(self, mock_github_class):
        result = _get_full_repo_names(self.slack_integration)

        assert result == []
        assert cache.get(_repo_list_cache_key(self.team.id)) == []
        mock_github_class.assert_not_called()

    def test_empty_result_with_github_integrations_not_cached(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = []
        mock_github_class.return_value = mock_github

        result = _get_full_repo_names(self.slack_integration)

        assert result == []
        assert cache.get(_repo_list_cache_key(self.team.id)) is None

    def test_signal_invalidates_on_github_save(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration)
        assert cache.get(_repo_list_cache_key(self.team.id)) is not None

        Integration.objects.create(
            team=self.team,
            kind="github",
            integration_id="gh-new",
            config={"account": {"name": "new-org"}},
            sensitive_config={"access_token": "ghp-new"},
        )

        assert cache.get(_repo_list_cache_key(self.team.id)) is None

    def test_signal_invalidates_on_github_delete(self, mock_github_class):
        gh_record = self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration)
        assert cache.get(_repo_list_cache_key(self.team.id)) is not None

        gh_record.delete()

        assert cache.get(_repo_list_cache_key(self.team.id)) is None

    def test_signal_ignores_non_github_integration(self, mock_github_class):
        self._create_github_integration()
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _get_full_repo_names(self.slack_integration)
        assert cache.get(_repo_list_cache_key(self.team.id)) is not None

        Integration.objects.create(
            team=self.team,
            kind="slack",
            integration_id="S99",
            sensitive_config={"access_token": "xoxb-other"},
        )

        assert cache.get(_repo_list_cache_key(self.team.id)) is not None


@patch("products.slack_app.backend.api.GitHubIntegration")
class TestPostRepoPickerPrewarm:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        cache.clear()
        self.organization = Organization.objects.create(name="Prewarm Org")
        self.team = Team.objects.create(organization=self.organization, name="Prewarm Team")
        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T_PREWARM",
            sensitive_config={"access_token": "xoxb-prewarm"},
        )

    @patch("products.slack_app.backend.api.SlackIntegration")
    def test_prewarm_calls_get_full_repo_names(self, mock_slack_cls, mock_github_class):
        from products.slack_app.backend.api import _post_repo_picker_message

        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )
        mock_github = MagicMock()
        mock_github.list_repositories.return_value = [_repo_dict("posthog", "repo-a")]
        mock_github_class.return_value = mock_github

        _post_repo_picker_message(
            slack=mock_slack,
            integration=self.slack_integration,
            channel="C001",
            thread_ts="123.456",
            slack_user_id="U001",
            event_text="fix bug",
            user_message_ts=None,
            guidance="Pick a repo",
            action_id="posthog_code_repo_select",
        )

        assert cache.get(_repo_list_cache_key(self.team.id)) == ["posthog/repo-a"]


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

        self.slack_integration = Integration.objects.create(
            team=self.team,
            kind="slack-posthog-code",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

        self.thread_messages = [{"user": "Dev", "text": "please update readme"}]

    def test_single_connected_repo_auto(self):
        decision = select_repository(
            event_text="please update readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog"
        assert decision.reason == "single_repo"
        assert decision.llm_found_match is False

    def test_explicit_repo_auto(self):
        decision = select_repository(
            event_text="fix posthog/posthog-js",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "explicit_mention"
        assert decision.llm_found_match is False

    def test_explicit_repo_takes_precedence_over_rules(self):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="anything about JS",
            repository="posthog/posthog",
            priority=0,
        )

        decision = select_repository(
            event_text="fix posthog/posthog-js",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "explicit_mention"

    @patch("products.slack_app.backend.api._match_repo_rule", return_value="posthog/posthog-js")
    def test_rule_match_auto(self, _mock_match):
        decision = select_repository(
            event_text="fix the JS SDK bug",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "rule_match"
        assert decision.llm_found_match is True

    @patch("products.slack_app.backend.api._match_repo_rule", return_value=None)
    def test_no_rule_match_picker(self, _mock_match):
        decision = select_repository(
            event_text="fix other/repo",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
        )

        assert decision.mode == "picker"
        assert decision.repository is None
        assert decision.reason == "no_rule_match"
        assert decision.llm_found_match is False

    def test_no_repos_picker(self):
        decision = select_repository(
            event_text="add yolo to readme",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=[],
        )

        assert decision.mode == "picker"
        assert decision.repository is None
        assert decision.reason == "no_repos"
        assert decision.llm_found_match is False

    def test_user_default_preference(self):
        user = User.objects.create(email="pref@example.com", distinct_id="pref-user")
        UserRepoPreference.set_default(
            team_id=self.team.id,
            user_id=user.id,
            scope_type="slack_channel",
            scope_id="C001",
            repository="posthog/posthog-js",
        )

        decision = select_repository(
            event_text="fix the bug",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js", "posthog/plugin-server"],
            user_id=user.id,
            channel="C001",
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "user_default"
        assert decision.llm_found_match is False

    def test_user_default_ignored_when_repo_not_connected(self):
        user = User.objects.create(email="pref2@example.com", distinct_id="pref-user-2")
        UserRepoPreference.set_default(
            team_id=self.team.id,
            user_id=user.id,
            scope_type="slack_channel",
            scope_id="C001",
            repository="posthog/disconnected-repo",
        )

        decision = select_repository(
            event_text="fix the bug",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js"],
            user_id=user.id,
            channel="C001",
        )

        assert decision.reason != "user_default"

    def test_explicit_mention_takes_precedence_over_user_default(self):
        user = User.objects.create(email="pref3@example.com", distinct_id="pref-user-3")
        UserRepoPreference.set_default(
            team_id=self.team.id,
            user_id=user.id,
            scope_type="slack_channel",
            scope_id="C001",
            repository="posthog/posthog",
        )

        decision = select_repository(
            event_text="fix posthog/posthog-js",
            thread_messages=self.thread_messages,
            integration=self.slack_integration,
            all_repos=["posthog/posthog", "posthog/posthog-js"],
            user_id=user.id,
            channel="C001",
        )

        assert decision.mode == "auto"
        assert decision.repository == "posthog/posthog-js"
        assert decision.reason == "explicit_mention"


class TestMatchRepoRule:
    @pytest.fixture(autouse=True)
    def setup(self, db):
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")

    def test_no_rules_returns_none(self):
        result = _match_repo_rule("fix bug", [{"user": "Dev", "text": "fix bug"}], self.team.id, ["org/repo"])
        assert result is None

    def test_no_eligible_rules_returns_none(self):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS issues",
            repository="org/disconnected-repo",
            priority=0,
        )
        result = _match_repo_rule("fix bug", [{"user": "Dev", "text": "fix bug"}], self.team.id, ["org/repo"])
        assert result is None

    @patch("products.slack_app.backend.api.get_llm_client")
    def test_llm_returns_valid_index(self, mock_get_client):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS SDK issues",
            repository="org/js-sdk",
            priority=0,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"rule_index": 0}'
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        result = _match_repo_rule(
            "fix the JS SDK", [{"user": "Dev", "text": "fix the JS SDK"}], self.team.id, ["org/js-sdk", "org/other"]
        )
        assert result == "org/js-sdk"

    @patch("products.slack_app.backend.api.get_llm_client")
    def test_llm_returns_null_index(self, mock_get_client):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS SDK issues",
            repository="org/js-sdk",
            priority=0,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"rule_index": null}'
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        result = _match_repo_rule(
            "unrelated request", [{"user": "Dev", "text": "unrelated"}], self.team.id, ["org/js-sdk"]
        )
        assert result is None

    @patch("products.slack_app.backend.api.get_llm_client")
    def test_llm_returns_invalid_index(self, mock_get_client):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS SDK issues",
            repository="org/js-sdk",
            priority=0,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"rule_index": 99}'
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        result = _match_repo_rule("fix bug", [{"user": "Dev", "text": "fix bug"}], self.team.id, ["org/js-sdk"])
        assert result is None

    @patch("products.slack_app.backend.api.get_llm_client")
    def test_llm_failure_returns_none(self, mock_get_client):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS SDK issues",
            repository="org/js-sdk",
            priority=0,
        )

        mock_get_client.return_value.chat.completions.create.side_effect = RuntimeError("LLM down")

        result = _match_repo_rule("fix bug", [{"user": "Dev", "text": "fix bug"}], self.team.id, ["org/js-sdk"])
        assert result is None

    @patch("products.slack_app.backend.api.get_llm_client")
    def test_llm_invalid_json_returns_none(self, mock_get_client):
        RepoRoutingRule.objects.create(
            team=self.team,
            rule_text="JS SDK issues",
            repository="org/js-sdk",
            priority=0,
        )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "not json"
        mock_get_client.return_value.chat.completions.create.return_value = mock_response

        result = _match_repo_rule("fix bug", [{"user": "Dev", "text": "fix bug"}], self.team.id, ["org/js-sdk"])
        assert result is None


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
                "default_repo_set",
                "default repo set org/repo",
                RulesCommand(action="default_set", repository="org/repo"),
            ),
            (
                "default_repo_set_bot",
                "<@U123BOT> default repo set my-org/my.repo",
                RulesCommand(action="default_set", repository="my-org/my.repo"),
            ),
            ("default_repo_show", "default repo show", RulesCommand(action="default_show")),
            ("default_repo_show_bot", "<@U123BOT> default repo show", RulesCommand(action="default_show")),
            ("default_repo_clear", "default repo clear", RulesCommand(action="default_clear")),
            ("default_repo_clear_bot", "<@U123BOT> default repo clear", RulesCommand(action="default_clear")),
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
            kind="slack-posthog-code",
            integration_id="T12345",
            sensitive_config={"access_token": "xoxb-test"},
        )

        self.channel = "C001"
        self.thread_ts = "1234567890.123456"
        self.slack_user_id = "U_SLACK"

    def _make_inputs(self, text: str):
        from posthog.temporal.ai.posthog_code_slack_mention import PostHogCodeSlackMentionWorkflowInputs

        return PostHogCodeSlackMentionWorkflowInputs(
            event={"text": text, "channel": self.channel, "thread_ts": self.thread_ts, "user": self.slack_user_id},
            integration_id=self.integration.id,
            slack_team_id="T12345",
        )

    @patch("posthog.models.integration.SlackIntegration")
    def test_list_empty_rules(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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
    def test_list_shows_rules(self, mock_slack_cls):
        mock_slack = MagicMock()
        mock_slack_cls.return_value = mock_slack

        RepoRoutingRule.objects.create(
            team=self.team, rule_text="JS SDK bugs", repository="posthog/posthog-js", priority=0
        )
        RepoRoutingRule.objects.create(
            team=self.team, rule_text="Backend issues", repository="posthog/posthog", priority=1
        )

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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
        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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

        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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
        from posthog.temporal.ai.posthog_code_slack_mention import handle_posthog_code_rules_command_activity

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
