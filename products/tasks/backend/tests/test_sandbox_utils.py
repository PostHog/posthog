import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration

from products.tasks.backend.temporal.process_task.utils import get_readonly_github_token, get_sandbox_api_url


@pytest.mark.parametrize(
    "sandbox_api_url, expected",
    [
        ("https://xxx.ngrok.dev", "https://xxx.ngrok.dev"),
        (None, "http://localhost:8010"),
    ],
    ids=["uses_sandbox_api_url_when_set", "falls_back_to_site_url_when_none"],
)
def test_get_sandbox_api_url(sandbox_api_url: str | None, expected: str) -> None:
    with override_settings(SANDBOX_API_URL=sandbox_api_url, SITE_URL="http://localhost:8010"):
        assert get_sandbox_api_url() == expected


def _team_integration_with_failing_mint() -> MagicMock:
    github = MagicMock(spec=GitHubIntegration)
    github.mint_scoped_installation_token.side_effect = GitHubIntegrationError("mint failed")
    return github


@pytest.mark.parametrize(
    "resolved",
    [None, _team_integration_with_failing_mint(), MagicMock(spec=UserGitHubIntegration)],
    ids=["no_integration", "mint_raises", "personal_integration_fallback"],
)
def test_get_readonly_github_token_never_raises_and_refuses_personal_integrations(
    resolved: MagicMock | None,
) -> None:
    # Read-only GitHub access is best-effort: an escaping exception here would fail sandbox
    # provisioning for every run that requested it whenever GitHub hiccups. The resolver's
    # org-owner fallback returns a *personal* integration whose installation can span repos never
    # connected to the team — minting off it would silently widen a scheduled scout's reach, so it
    # must be refused, not used.
    with patch(
        "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration",
        return_value=resolved,
    ):
        assert get_readonly_github_token(1) is None
    if resolved is not None and not isinstance(resolved, GitHubIntegration):
        resolved.mint_scoped_installation_token.assert_not_called()
