import pytest

from products.tasks.backend.exceptions import SandboxMissingRepositoryError
from products.tasks.backend.logic.services.sandbox import ExecutionResult, sandbox_repo_path
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    StartAgentServerInput,
    _ensure_repository_on_disk,
    _resolve_protected_base_branch,
    start_agent_server,
)


def _context(
    *,
    sandbox_event_ingest_enabled: bool = False,
    github_integration_id: int | None = None,
    repository: str | None = None,
    branch: str | None = None,
    state: dict | None = None,
) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id="task-id",
        run_id="run-id",
        team_id=1,
        team_uuid="team-uuid",
        organization_id="organization-id",
        github_integration_id=github_integration_id,
        repository=repository,
        distinct_id="distinct-id",
        state=state,
        sandbox_event_ingest_enabled=sandbox_event_ingest_enabled,
        _branch=branch,
    )


def _mock_github_integration(mocker, pr_base: str | None):
    integration = mocker.Mock()
    integration.access_token_expired.return_value = False
    integration.get_open_pr_base_for_head.return_value = pr_base
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Integration.objects.get",
        return_value=mocker.Mock(),
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.GitHubIntegration",
        return_value=integration,
    )
    return integration


@pytest.mark.parametrize(
    "pr_base,branch,expected",
    [
        # Quick action started on an existing PR head: protect the PR's base, not the head.
        ("master", "posthog-code/ci-test-break", "master"),
        # New task started off a base branch: keep protecting it (the agent branches off it).
        (None, "release/direct-upload", "release/direct-upload"),
        # No working branch: nothing to protect.
        (None, None, None),
    ],
)
def test_resolve_protected_base_branch(mocker, pr_base, branch, expected) -> None:
    _mock_github_integration(mocker, pr_base=pr_base)
    context = _context(github_integration_id=42, repository="PostHog/posthog", branch=branch)
    assert _resolve_protected_base_branch(context) == expected


def test_resolve_protected_base_skips_lookup_without_repository(mocker) -> None:
    # Repo-less runs (e.g. Slack) must pass the branch through untouched, with no GitHub lookup.
    get = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Integration.objects.get",
    )
    context = _context(github_integration_id=42, repository=None, branch="some-branch")
    assert _resolve_protected_base_branch(context) == "some-branch"
    get.assert_not_called()


def test_resolve_protected_base_falls_back_to_branch_on_error(mocker) -> None:
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Integration.objects.get",
        side_effect=RuntimeError("boom"),
    )
    context = _context(github_integration_id=42, repository="PostHog/posthog", branch="posthog-code/fix")
    assert _resolve_protected_base_branch(context) == "posthog-code/fix"


def test_ensure_repository_on_disk_passes_when_repo_present(mocker) -> None:
    sandbox = mocker.Mock()
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)

    _ensure_repository_on_disk(_context(repository="PostHog/posthog"), sandbox)

    # The precheck must probe the same path the clone writes to.
    assert sandbox_repo_path("PostHog/posthog") in sandbox.execute.call_args.args[0]


def test_ensure_repository_on_disk_fails_non_retryably_when_repo_missing(mocker) -> None:
    # Without this, a run whose repo was never cloned (no snapshot, no GitHub credentials) burns
    # repeated 5-minute health-check timeouts and fails with a misleading "Failed to start agent
    # server" instead of the actual reason.
    sandbox = mocker.Mock()
    sandbox.id = "sandbox-id"
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=1)
    mocker.patch("products.tasks.backend.exceptions.capture_exception")

    with pytest.raises(SandboxMissingRepositoryError) as exc_info:
        _ensure_repository_on_disk(_context(repository="PostHog/posthog"), sandbox)

    assert exc_info.value.non_retryable is True
    assert "never" in str(exc_info.value)


def test_ensure_repository_on_disk_skips_repo_less_runs(mocker) -> None:
    sandbox = mocker.Mock()

    _ensure_repository_on_disk(_context(repository=None), sandbox)

    sandbox.execute.assert_not_called()


async def test_start_agent_server_uses_captured_sandbox_event_ingest_flag(mocker) -> None:
    context = _context(sandbox_event_ingest_enabled=True)
    sandbox = mocker.Mock()
    sandbox.execute.return_value.stdout = ""
    sandbox.execute.return_value.stderr = ""
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch("products.tasks.backend.temporal.process_task.activities.start_agent_server.emit_agent_log")
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value.get.return_value = mocker.Mock(created_by_id=None)
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.objects.get",
        return_value=mocker.Mock(),
    )
    create_event_ingest_token = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_sandbox_event_ingest_token",
        return_value="event-ingest-token",
    )

    result = await start_agent_server(
        StartAgentServerInput(
            context=context,
            sandbox_id="sandbox-id",
            sandbox_url="https://sandbox.example",
            sandbox_connect_token="connect-token",
        )
    )

    assert result.sandbox_url == "https://sandbox.example"
    assert result.connect_token == "connect-token"
    create_event_ingest_token.assert_called_once()
    sandbox.start_agent_server.assert_called_once()
    assert sandbox.start_agent_server.call_args.kwargs["event_ingest_token"] == "event-ingest-token"


async def test_start_agent_server_passes_initial_permission_mode(mocker) -> None:
    context = _context(state={"initial_permission_mode": "plan"})
    sandbox = mocker.Mock()
    sandbox.execute.return_value.stdout = ""
    sandbox.execute.return_value.stderr = ""
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch("products.tasks.backend.temporal.process_task.activities.start_agent_server.emit_agent_log")
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value.get.return_value = mocker.Mock(created_by_id=None)
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )

    await start_agent_server(
        StartAgentServerInput(
            context=context,
            sandbox_id="sandbox-id",
            sandbox_url="https://sandbox.example",
            sandbox_connect_token="connect-token",
        )
    )

    sandbox.start_agent_server.assert_called_once()
    assert sandbox.start_agent_server.call_args.kwargs["initial_permission_mode"] == "plan"
