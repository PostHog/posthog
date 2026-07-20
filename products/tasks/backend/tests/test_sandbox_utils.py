import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import UserGitHubIntegration

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.utils import (
    can_mint_readonly_github_token,
    get_readonly_github_token,
    get_sandbox_api_url,
)


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


@pytest.mark.parametrize(
    "resolved, expected",
    [
        (MagicMock(spec=GitHubIntegration), True),
        (MagicMock(spec=UserGitHubIntegration), False),
        (None, False),
        (GitHubIntegrationError("resolver blew up"), False),
    ],
    ids=["team_integration", "personal_integration", "no_integration", "resolver_raises"],
)
def test_can_mint_readonly_github_token_matches_mint_eligibility(resolved, expected: bool) -> None:
    # The preflight gates whether prompts name `gh` at all — a wrong True steers agents into
    # 401s on teams that never connected GitHub; raising would fail the run it's protecting.
    with patch("products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration") as mock_resolve:
        if isinstance(resolved, Exception):
            mock_resolve.side_effect = resolved
        else:
            mock_resolve.return_value = resolved
        assert can_mint_readonly_github_token(1) is expected


@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.emit_agent_log")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_readonly_github_token")
def test_readonly_request_takes_priority_over_full_credential_path(
    mock_readonly: MagicMock, mock_full: MagicMock, _mock_log: MagicMock
) -> None:
    # Task creation attaches the team's GitHub integration to every task, so a repo-less run on a
    # GitHub-connected team satisfies the full-credential condition too. If the full path is
    # resolved first, a run that asked for read-only silently receives the write-capable
    # installation token — the exact escalation this ordering exists to prevent.
    from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (  # noqa: PLC0415 — activities import the workflow stack; keep it off this module's import path
        _resolve_sandbox_github_token,
    )

    mock_readonly.return_value = "READONLY_TOKEN"
    ctx = TaskProcessingContext(
        task_id="t",
        run_id="r",
        team_id=1,
        team_uuid="u",
        organization_id="o",
        github_integration_id=5,
        repository=None,
        distinct_id="d",
        state={"github_read_access": True},
    )

    token = _resolve_sandbox_github_token(ctx, task=MagicMock(), actor_user=None, repository=None, has_repo=False)

    assert token == "READONLY_TOKEN"
    mock_full.assert_not_called()
