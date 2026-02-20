import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.integration import Integration
from posthog.models.organization import Organization
from posthog.models.team.team import Team
from posthog.models.user import User

from products.slack_app.backend.api import guess_repository


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
    @patch("products.slack_app.backend.api.get_llm_client")
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
