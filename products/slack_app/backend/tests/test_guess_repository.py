import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import _extract_explicit_repo, guess_repository, select_repository
from products.slack_app.backend.models import SlackUserRepoPreference


def _make_llm_response(content: str) -> MagicMock:
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = content
    return mock_response


class TestGuessRepository:
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

        self.github_integration = Integration.objects.create(
            team=self.team,
            kind="github",
            config={"account": {"name": "posthog"}},
            sensitive_config={"access_token": "ghp-test"},
        )

    @parameterized.expand(
        [
            ("single_match", "posthog/posthog-js", ["posthog/posthog-js"]),
            ("multiple_matches", "posthog/posthog-js\nposthog/posthog", ["posthog/posthog-js", "posthog/posthog"]),
            ("no_match", "", []),
            ("invalid_repo_filtered", "posthog/nonexistent", []),
        ]
    )
    @patch("posthog.llm.gateway_client.get_llm_client")
    @patch("products.slack_app.backend.api.GitHubIntegration")
    def test_guess_repository(self, _name, llm_output, expected, mock_github_class, mock_get_llm):
        mock_github = MagicMock()
        mock_github.organization.return_value = "posthog"
        mock_github.list_repositories.return_value = ["posthog-js", "posthog", "plugin-server"]
        mock_github_class.return_value = mock_github

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _make_llm_response(llm_output)
        mock_get_llm.return_value = mock_client

        messages = [{"user": "Dev", "text": "fix the bug in posthog-js"}]
        result = guess_repository(messages, self.slack_integration)

        assert result == expected

    def test_no_github_integration(self):
        self.github_integration.delete()
        messages = [{"user": "Dev", "text": "fix the bug"}]
        result = guess_repository(messages, self.slack_integration)
        assert result == []


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
        SlackUserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            channel=self.channel,
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
        SlackUserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            channel="C_OTHER",
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
        SlackUserRepoPreference.objects.create(
            team=self.team,
            user=self.user,
            channel=self.channel,
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
        assert SlackUserRepoPreference.objects.filter(team=self.team, user=self.user, channel=self.channel).count() == 0

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
