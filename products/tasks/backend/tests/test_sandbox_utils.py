from datetime import timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.test import override_settings

import requests
from parameterized import parameterized
from temporalio.testing import ActivityEnvironment

from posthog.egress.github.transport import GitHubRateLimitError
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import GitHubIntegration
from posthog.models.user_integration import ReauthorizationRequired, UserGitHubIntegration

from products.tasks.backend.exceptions import (
    CredentialUnavailableError,
    GitHubAuthenticationError,
    GitHubRateLimitedError,
    ProcessTaskTransientError,
)
from products.tasks.backend.redis import get_tasks_cache
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.utils import (
    READONLY_SANDBOX_GITHUB_PERMISSIONS,
    can_mint_readonly_github_token,
    forget_cached_github_tokens,
    get_readonly_github_token,
    get_sandbox_api_url,
)


@pytest.fixture(autouse=True)
def _isolated_tasks_cache(settings):
    settings.TASKS_REDIS_URL = ""
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    get_tasks_cache().clear()


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


def _team_integration(*, unavailable: bool = False, mint_raises: bool = False) -> MagicMock:
    github = MagicMock(spec=GitHubIntegration)
    github.github_installation_id = "INSTALL"
    github.mint_scoped_installation_token.return_value = "ghs_readonly"
    github.installation_unavailable.return_value = unavailable
    github.account_name_needs_heal.return_value = False
    github.organization.return_value = "Acme"
    if mint_raises:
        github.mint_scoped_installation_token.side_effect = GitHubIntegrationError("mint failed")
    return github


@pytest.mark.parametrize(
    "resolved",
    [
        None,
        _team_integration(mint_raises=True),
        MagicMock(spec=UserGitHubIntegration),
        _team_integration(unavailable=True),
    ],
    ids=["no_integration", "mint_raises", "personal_integration_fallback", "installation_marked_gone"],
)
def test_get_readonly_github_token_never_raises_and_refuses_personal_integrations(
    resolved: MagicMock | None,
) -> None:
    # Read-only GitHub access is best-effort: an escaping exception here would fail sandbox
    # provisioning for every run that requested it whenever GitHub hiccups. The resolver's
    # org-owner fallback returns a *personal* integration whose installation can span repos never
    # connected to the team — minting off it would silently widen a scheduled scout's reach, so it
    # must be refused, not used. An installation a prior mint marked permanently gone must also be
    # skipped without minting, or every scheduled run re-storms GitHub with doomed calls.
    with patch(
        "products.tasks.backend.logic.repo_selection.agent.resolve_team_github_integration",
        return_value=resolved,
    ):
        assert get_readonly_github_token(1) is None
    if resolved is not None and (
        not isinstance(resolved, GitHubIntegration) or resolved.installation_unavailable.return_value
    ):
        resolved.mint_scoped_installation_token.assert_not_called()


@pytest.mark.parametrize(
    "resolved, expected",
    [
        (_team_integration(), True),
        (MagicMock(spec=UserGitHubIntegration), False),
        (None, False),
        (GitHubIntegrationError("resolver blew up"), False),
        (_team_integration(unavailable=True), False),
    ],
    ids=["team_integration", "personal_integration", "no_integration", "resolver_raises", "installation_marked_gone"],
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


@parameterized.expand(
    [
        ("full_credential_run_reuses", False, 5),
        ("read_only_run_clones_fresh", True, None),
    ]
)
def test_repository_snapshot_reuse_is_refused_for_read_only_runs(
    _name: str, read_access: bool, expected: int | None
) -> None:
    # A repository snapshot keeps its creator's write-capable token in every `.git/config` and is
    # never fetched again, so restoring one for a read-only run hands the agent a write token and
    # a stale tree. A Signals scout with pinned repositories is exactly that run.
    from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (  # noqa: PLC0415 — activities import the workflow stack; keep it off this module's import path
        _repository_snapshot_integration_id,
    )

    ctx = TaskProcessingContext(
        task_id="t",
        run_id="r",
        team_id=1,
        team_uuid="u",
        organization_id="o",
        github_integration_id=5,
        repository="acme/app",
        distinct_id="d",
        state={"github_read_access": read_access},
    )

    assert _repository_snapshot_integration_id(ctx, has_repo=True) == expected


@parameterized.expand(
    [
        ("repo_less", None, False, True),
        ("repo_backed", "acme/repo", True, True),
        ("mint_unavailable", None, False, False),
    ]
)
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.emit_agent_log")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.TaskRun.update_state_atomic")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_readonly_github_token")
def test_readonly_request_takes_priority_over_full_credential_path(
    _name: str,
    repository: str | None,
    has_repo: bool,
    token_available: bool,
    mock_readonly: MagicMock,
    mock_full: MagicMock,
    mock_state: MagicMock,
    _mock_log: MagicMock,
) -> None:
    # Task creation attaches the team's GitHub integration to every task, so a run on a
    # GitHub-connected team satisfies the full-credential condition too. If the full path is
    # resolved first, a run that asked for read-only silently receives the write-capable
    # installation token — the exact escalation this ordering exists to prevent.
    #
    # The repo-backed case is the one a Signals scout with pinned repositories takes. Gating the
    # downscope on "no repository" would hand every such scout a write-capable token as a side
    # effect of cloning, which is a fleet-wide escalation delivered by a feature about checkouts.
    from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (  # noqa: PLC0415 — activities import the workflow stack; keep it off this module's import path
        _resolve_sandbox_github_token,
    )

    mock_readonly.return_value = "READONLY_TOKEN" if token_available else None
    ctx = TaskProcessingContext(
        task_id="t",
        run_id="r",
        team_id=1,
        team_uuid="u",
        organization_id="o",
        github_integration_id=5,
        repository=repository,
        distinct_id="d",
        state={"github_read_access": True},
    )

    token = _resolve_sandbox_github_token(
        ctx, task=MagicMock(), actor_user=None, repository=repository, has_repo=has_repo
    )

    mock_readonly.assert_called_once_with(ctx.team_id, repositories=ctx.repositories)
    assert token == ("READONLY_TOKEN" if token_available else "")
    mock_state.assert_called_once_with(ctx.run_id, updates={"github_read_access_available": token_available})
    mock_full.assert_not_called()


@pytest.mark.parametrize(
    "github_integration_id, expected",
    [(5, "FULL_TOKEN"), (None, "")],
    ids=["entitled_discussion_gets_the_team_credential", "unentitled_discussion_stays_credential_less"],
)
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.emit_agent_log")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token")
def test_repo_less_report_run_follows_the_integration_the_create_path_attached(
    mock_full: MagicMock, _mock_log: MagicMock, github_integration_id: int | None, expected: str
) -> None:
    # Ask AI on a report runs repo-less, and it used to get no credential whatever it carried, so
    # it could not clone a private repository or push. The attached integration is the signal now:
    # the create path attaches one only after the Desktop gate passed, and a scout or scout-chat
    # task never gets one at all.
    from products.tasks.backend.models import Task  # noqa: PLC0415 — model import kept off this module's import path
    from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (  # noqa: PLC0415 — activities import the workflow stack; keep it off this module's import path
        _resolve_sandbox_github_token,
    )

    mock_full.return_value = "FULL_TOKEN"
    task = Task(origin_product=Task.OriginProduct.SIGNAL_REPORT)
    ctx = TaskProcessingContext(
        task_id="t",
        run_id="r",
        team_id=1,
        team_uuid="u",
        organization_id="o",
        github_integration_id=github_integration_id,
        repository=None,
        distinct_id="d",
        state={},
    )

    token = _resolve_sandbox_github_token(ctx, task=task, actor_user=None, repository=None, has_repo=False)

    assert token == expected


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize(
    "error, cause, expected_error",
    [
        (ReauthorizationRequired("relink GitHub"), None, CredentialUnavailableError),
        (
            CredentialUnavailableError("missing repository", {"repositories": ["acme/repo"]}),
            None,
            CredentialUnavailableError,
        ),
        (GitHubRateLimitError("limited", retry_after=30), None, GitHubRateLimitedError),
        (requests.ConnectionError("reset"), None, ProcessTaskTransientError),
        (GitHubIntegrationError("network error"), requests.ConnectionError("reset"), ProcessTaskTransientError),
        (GitHubIntegrationError("bad gateway", status_code=502), None, ProcessTaskTransientError),
        (
            GitHubIntegrationError("token refresh failed"),
            GitHubIntegrationError("service unavailable", status_code=503),
            ProcessTaskTransientError,
        ),
        (
            GitHubIntegrationError("token refresh failed"),
            GitHubRateLimitError("limited", retry_after=30),
            GitHubRateLimitedError,
        ),
        (
            GitHubIntegrationError("token refresh failed"),
            GitHubIntegrationError("unauthorized", status_code=401),
            GitHubAuthenticationError,
        ),
        (GitHubIntegrationError("not accessible", status_code=422), None, GitHubAuthenticationError),
    ],
    ids=[
        "reauthorization",
        "unavailable_credential",
        "rate_limited",
        "connection_error",
        "wrapped_connection_error",
        "server_error",
        "wrapped_server_error",
        "wrapped_rate_limit",
        "wrapped_authentication_error",
        "rejected_mint",
    ],
)
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.emit_agent_log")
@patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_sandbox_github_token")
async def test_github_token_failure_maps_to_run_error(
    mock_full: MagicMock,
    _mock_log: MagicMock,
    error: Exception,
    cause: Exception | None,
    expected_error: type[Exception],
    resume: bool,
) -> None:
    # ReauthorizationRequired is a user-actionable "re-link your GitHub account" signal, not a
    # system fault. Provisioning must surface it as CredentialUnavailableError (fatal, non-retryable,
    # not captured to error tracking) rather than wrapping it in GitHubAuthenticationError, which
    # captures the raw exception and floods error tracking with noise.
    from products.tasks.backend.temporal.process_task.activities.provision_sandbox import (  # noqa: PLC0415 — activities import the workflow stack; keep it off this module's import path
        InjectFreshTokensOnResumeInput,
        _resolve_sandbox_github_token,
        inject_fresh_tokens_on_resume,
    )

    error.__cause__ = cause
    mock_full.side_effect = error
    ctx = TaskProcessingContext(
        task_id="t",
        run_id="r",
        team_id=1,
        team_uuid="u",
        organization_id="o",
        github_integration_id=5,
        repository="acme/repo",
        distinct_id="d",
        state={},
    )

    with (
        patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox._load_task"),
        patch("products.tasks.backend.temporal.process_task.activities.provision_sandbox.get_task_run_credential_user"),
        pytest.raises(expected_error) as raised,
    ):
        if resume:
            await ActivityEnvironment().run(
                inject_fresh_tokens_on_resume,
                InjectFreshTokensOnResumeInput(context=ctx, sandbox_id="sandbox-id", repository="acme/repo"),
            )
        else:
            _resolve_sandbox_github_token(ctx, task=MagicMock(), actor_user=None, repository="acme/repo", has_repo=True)
    assert type(raised.value) is expected_error
    if isinstance(error, CredentialUnavailableError):
        assert raised.value is error
    if isinstance(raised.value, GitHubRateLimitedError):
        assert raised.value.next_retry_delay == timedelta(seconds=30)


def test_readonly_token_is_still_minted_when_the_cache_fails():
    integration = _team_integration()
    broken_cache = MagicMock()
    broken_cache.get.side_effect = ConnectionError("redis down")
    broken_cache.set.side_effect = ConnectionError("redis down")
    with (
        patch(
            "products.tasks.backend.temporal.process_task.utils.resolve_readonly_github_integration",
            return_value=integration,
        ),
        patch("products.tasks.backend.temporal.process_task.utils.get_tasks_cache", return_value=broken_cache),
    ):
        token = get_readonly_github_token(1, repositories=["acme/api"])

    assert token == "ghs_readonly"
    integration.mint_scoped_installation_token.assert_called_once()


def test_readonly_token_is_reused_until_forgotten():
    integration = _team_integration()
    integration.mint_scoped_installation_token.side_effect = ["ghs_ro_1", "ghs_ro_2"]
    with patch(
        "products.tasks.backend.temporal.process_task.utils.resolve_readonly_github_integration",
        return_value=integration,
    ):
        first = [get_readonly_github_token(1, repositories=["acme/api"]) for _ in range(2)]
        forget_cached_github_tokens(integration, ["acme/api"])
        second = get_readonly_github_token(1, repositories=["acme/api"])

    assert first == ["ghs_ro_1", "ghs_ro_1"]
    assert second == "ghs_ro_2"
    assert integration.mint_scoped_installation_token.call_count == 2


@pytest.mark.parametrize(
    "repositories, mints, expected",
    [
        ([], True, None),
        (["Acme/API", "acme/api", "acme/web"], True, ["api", "web"]),
        (["PostHog/.github"], True, None),
        (["evilorg/api"], False, None),
    ],
    ids=["repo_less", "pinned_repositories", "public_bootstrap_only", "another_account_only"],
)
def test_readonly_token_scopes_repositories_without_widening_permissions(repositories, mints, expected):
    integration = _team_integration()
    with patch(
        "products.tasks.backend.temporal.process_task.utils.resolve_readonly_github_integration",
        return_value=integration,
    ):
        token = get_readonly_github_token(1, repositories=repositories)
    if mints:
        assert token == integration.mint_scoped_installation_token.return_value
        integration.mint_scoped_installation_token.assert_called_once_with(
            READONLY_SANDBOX_GITHUB_PERMISSIONS, repositories=expected
        )
    else:
        assert token is None
        integration.mint_scoped_installation_token.assert_not_called()
