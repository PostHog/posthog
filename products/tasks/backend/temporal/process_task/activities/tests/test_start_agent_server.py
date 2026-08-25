import pytest
from freezegun import freeze_time

from django.db import OperationalError

from products.tasks.backend.exceptions import OAuthTokenError, SandboxExecutionError, SandboxMissingRepositoryError
from products.tasks.backend.logic.services.sandbox import ExecutionResult, sandbox_repo_path
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    StartAgentServerInput,
    _agentsh_domains_for,
    _ensure_repository_on_disk,
    _include_personal_mcp_for_task,
    _LaunchParams,
    _network_enforcement_observation,
    _prepare_launch,
    _record_boot_total,
    _resolve_protected_base_branch,
    await_agent_server_ready,
    start_agent_server,
)


@freeze_time("2026-08-06T12:01:30Z")
def test_record_boot_total_excludes_wizard_time_and_labels_runtime(mocker) -> None:
    record_metric = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.record_boot_total_ms"
    )
    input = StartAgentServerInput(
        context=_context(),
        sandbox_id="sandbox-id",
        sandbox_url="https://sandbox.example",
        workflow_start_at="2026-08-06T12:00:00+00:00",
        boot_excluded_ms=60_000,
    )

    assert _record_boot_total(input) == 30_000
    record_metric.assert_called_once_with(
        30_000,
        boot_path="classic",
        used_snapshot=None,
        has_repo=False,
        origin_product=None,
        runtime="gvisor",
    )


def _context(
    *,
    sandbox_event_ingest_enabled: bool = False,
    github_integration_id: int | None = None,
    repository: str | None = None,
    branch: str | None = None,
    state: dict | None = None,
    allowed_domains: list[str] | None = None,
    agentsh_domain_allowlist: list[str] | None = None,
    network_policy_fingerprint: str | None = None,
    use_modal_vm_sandbox: bool = False,
    use_modal_network_allowlist: bool = False,
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
        allowed_domains=allowed_domains,
        agentsh_domain_allowlist=agentsh_domain_allowlist,
        network_policy_fingerprint=network_policy_fingerprint,
        use_modal_vm_sandbox=use_modal_vm_sandbox,
        use_modal_network_allowlist=use_modal_network_allowlist,
        _branch=branch,
    )


@pytest.mark.parametrize(
    "context,expected_observation,expected_agentsh_domains",
    [
        (_context(), "unrestricted", None),
        (_context(allowed_domains=["example.com"]), "agentsh_ready", ["example.com"]),
        (
            _context(
                allowed_domains=["example.com"],
                agentsh_domain_allowlist=["example.com", "api.posthog.com"],
            ),
            "agentsh_ready",
            ["example.com", "api.posthog.com"],
        ),
        (
            _context(
                allowed_domains=["example.com"],
                agentsh_domain_allowlist=["example.com", "api.posthog.com"],
                use_modal_network_allowlist=True,
            ),
            "modal_requested_sandbox_created_agentsh_ready",
            ["example.com", "api.posthog.com"],
        ),
        (
            _context(
                allowed_domains=["example.com"],
                agentsh_domain_allowlist=["example.com", "api.posthog.com"],
                use_modal_vm_sandbox=True,
                use_modal_network_allowlist=True,
                network_policy_fingerprint="policy-hash",
            ),
            "modal_requested_sandbox_created_agentsh_ready",
            ["example.com", "api.posthog.com"],
        ),
    ],
)
def test_network_enforcement_observation_matches_completed_checks(
    context: TaskProcessingContext,
    expected_observation: str,
    expected_agentsh_domains: list[str] | None,
) -> None:
    assert _network_enforcement_observation(context) == expected_observation
    assert _agentsh_domains_for(context) == expected_agentsh_domains


async def test_start_failure_does_not_report_network_enforcement_observation(mocker) -> None:
    context = _context(
        allowed_domains=["example.com"],
        agentsh_domain_allowlist=["example.com", "api.posthog.com"],
        use_modal_vm_sandbox=True,
        use_modal_network_allowlist=True,
        network_policy_fingerprint="policy-hash",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=mocker.Mock(),
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._prepare_launch",
        return_value=mocker.Mock(),
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._invoke_start_agent_server",
        side_effect=RuntimeError("health check failed"),
    )
    record_observation = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._record_network_enforcement_observation"
    )

    with pytest.raises(RuntimeError, match="health check failed"):
        await start_agent_server(
            StartAgentServerInput(
                context=context,
                sandbox_id="sandbox-id",
                sandbox_url="https://sandbox.example",
            )
        )

    record_observation.assert_not_called()


@pytest.mark.parametrize(("attempt", "expects_relaunch"), [(1, False), (2, True), (3, True)])
async def test_await_agent_server_ready_relaunches_on_activity_retries(mocker, attempt, expects_relaunch) -> None:
    context = _context()
    sandbox = mocker.Mock(id="sandbox-id")
    sandbox.read_agent_server_session_init_ms.return_value = None
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.current_activity_attempt",
        return_value=attempt,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._prepare_launch",
        return_value=_LaunchParams(
            mcp_configs=[],
            relayed_mcp_servers=[],
            actor_user_id=None,
            agentsh_domains=None,
            protected_base_branch=None,
            event_ingest_token=None,
            task_run_session_token=None,
            event_ingest_url=None,
            event_ingest_keep_stream_open=False,
        ),
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.update_state_atomic"
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._record_network_enforcement_observation"
    )
    mocker.patch("products.tasks.backend.temporal.process_task.activities.start_agent_server.emit_agent_log")
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._spawn_post_ready_diagnostics"
    )
    record_retry = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.increment_agent_server_readiness_retry"
    )

    result = await await_agent_server_ready(
        StartAgentServerInput(
            context=context,
            sandbox_id="sandbox-id",
            sandbox_url="https://sandbox.example",
            boot_path="overlap",
        )
    )

    assert result.sandbox_url == "https://sandbox.example"
    if expects_relaunch:
        sandbox.wait_for_agent_server_ready.assert_not_called()
        sandbox.start_agent_server.assert_called_once()
        record_retry.assert_called_once_with(
            attempt,
            "succeeded",
            boot_path="overlap",
            origin_product=None,
            runtime="gvisor",
        )
    else:
        sandbox.wait_for_agent_server_ready.assert_called_once_with(None)
        sandbox.start_agent_server.assert_not_called()
        record_retry.assert_not_called()


async def test_await_agent_server_ready_records_failed_relaunch(mocker) -> None:
    context = _context()
    sandbox = mocker.Mock(id="sandbox-id")
    sandbox.start_agent_server.side_effect = RuntimeError("session did not initialize")
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.current_activity_attempt",
        return_value=2,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._prepare_launch",
        return_value=_LaunchParams(
            mcp_configs=[],
            relayed_mcp_servers=[],
            actor_user_id=None,
            agentsh_domains=None,
            protected_base_branch=None,
            event_ingest_token=None,
            task_run_session_token=None,
            event_ingest_url=None,
            event_ingest_keep_stream_open=False,
        ),
    )
    mocker.patch("products.tasks.backend.exceptions.capture_exception")
    mocker.patch("products.tasks.backend.temporal.process_task.activities.start_agent_server.emit_agent_log")
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server._emit_agent_server_log_tail"
    )
    record_retry = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.increment_agent_server_readiness_retry"
    )

    with pytest.raises(SandboxExecutionError, match="Failed to start agent server in sandbox"):
        await await_agent_server_ready(
            StartAgentServerInput(
                context=context,
                sandbox_id="sandbox-id",
                sandbox_url="https://sandbox.example",
                boot_path="overlap",
            )
        )

    record_retry.assert_called_once_with(
        2,
        "failed",
        boot_path="overlap",
        origin_product=None,
        runtime="gvisor",
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
    "internal,expected",
    [
        # Internal/autonomous runs (support reply, signals) get shared team
        # connections only — never a resolved member's personal MCP creds.
        (True, False),
        # User-initiated Code runs get shared + the creator's personal installs.
        (False, True),
    ],
)
def test_include_personal_mcp_for_task(mocker, internal, expected) -> None:
    task = mocker.Mock(internal=internal)
    assert _include_personal_mcp_for_task(task) is expected


def test_prepare_launch_retries_task_read_and_keeps_db_drop_identity(mocker) -> None:
    task_get = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value.get
    task_get.side_effect = [
        OperationalError("server conn crashed?"),
        OperationalError("server conn crashed?"),
    ]

    with pytest.raises(OperationalError):
        _prepare_launch(_context(), mocker.Mock(), "sandbox-id")

    assert task_get.call_count == 2


@pytest.mark.parametrize(
    "raised,expected",
    [
        (OperationalError("server conn crashed?"), OperationalError),
        (RuntimeError("token mint failed"), OAuthTokenError),
    ],
)
def test_prepare_launch_relabels_only_non_transient_token_errors(mocker, raised, expected) -> None:
    task = mocker.Mock(internal=True, created_by_id=None, team_id=1)
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value.get.return_value = task
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_task_run_credential_user",
        return_value=None,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token_for_run",
        side_effect=raised,
    )

    with pytest.raises(expected):
        _prepare_launch(_context(), mocker.Mock(), "sandbox-id")


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
    get = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Integration.objects.get",
    )
    context = _context(github_integration_id=42, repository=None, branch="some-branch")
    assert _resolve_protected_base_branch(context) is None
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


def test_ensure_every_repository_is_on_disk(mocker) -> None:
    sandbox = mocker.Mock()
    sandbox.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)

    _ensure_repository_on_disk(
        _context(
            repository="PostHog/posthog",
            state={"repositories": ["PostHog/posthog", "PostHog/posthog-js"]},
        ),
        sandbox,
    )

    assert [call.args[0] for call in sandbox.execute.call_args_list] == [
        f"test -d {sandbox_repo_path('PostHog/posthog')}",
        f"test -d {sandbox_repo_path('PostHog/posthog-js')}",
    ]


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


@pytest.mark.django_db
async def test_start_agent_server_uses_captured_sandbox_event_ingest_flag(mocker) -> None:
    context = _context(sandbox_event_ingest_enabled=True, state={"mcp_builtin_agent_key": "scout"})
    sandbox = mocker.Mock()
    sandbox.execute.return_value.stdout = ""
    sandbox.execute.return_value.stderr = ""
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
        return_value=sandbox,
    )
    mocker.patch("products.tasks.backend.temporal.process_task.activities.start_agent_server.emit_agent_log")
    task = mocker.Mock(
        created_by_id=None,
        team_id=1,
        internal=True,
        origin_product="support_reply",
        mcp_builtin_agent_key="support",
        mcp_credential_owner_id=17,
        mcp_gateway_server_allowlist=["srv-1"],
    )
    task_queryset = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.Task.objects.select_related"
    ).return_value
    task_queryset.get.return_value = task
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token_for_run",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )
    get_user_mcp_configs = mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_user_mcp_server_configs",
        return_value=[],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.objects.filter",
    ).return_value.first.return_value = mocker.Mock(state={}, imported_mcp_servers=None)
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
    assert create_event_ingest_token.call_args.kwargs == {"sandbox_id": "sandbox-id"}
    task_queryset.get.assert_called_once_with(id="task-id")
    get_user_mcp_configs.assert_called_once_with(
        token="oauth-token",
        team_id=1,
        user_id=None,
        include_personal=False,
        interaction_origin=None,
        allowed_installation_ids=None,
        origin_product="support_reply",
        task_agent_key="support",
        credential_owner_id=17,
        allowed_gateway_server_ids=["srv-1"],
    )
    sandbox.start_agent_server.assert_called_once()
    assert sandbox.start_agent_server.call_args.kwargs["event_ingest_token"] == "event-ingest-token"


async def test_start_agent_server_forwards_imported_and_relayed_mcp_servers(mocker) -> None:
    context = _context()
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
    ).return_value.get.return_value = mocker.Mock(
        created_by_id=None,
        team_id=1,
        internal=False,
        origin_product="user_created",
        mcp_builtin_agent_key=None,
        mcp_credential_owner_id=None,
        mcp_gateway_server_allowlist=None,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token_for_run",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.objects.filter",
    ).return_value.first.return_value = mocker.Mock(
        state={},
        imported_mcp_servers=[
            {"type": "http", "name": "linear", "url": "https://mcp.linear.app", "headers": []},
        ],
        relayed_mcp_servers=[{"name": "slack"}],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_sandbox_event_ingest_token",
        return_value="event-ingest-token",
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
    kwargs = sandbox.start_agent_server.call_args.kwargs
    assert [config.name for config in kwargs["mcp_configs"]] == ["linear"]
    assert kwargs["relayed_mcp_servers"] == ["slack"]


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
    ).return_value.get.return_value = mocker.Mock(
        created_by_id=None,
        team_id=1,
        internal=False,
        origin_product="user_created",
        mcp_builtin_agent_key=None,
        mcp_credential_owner_id=None,
        mcp_gateway_server_allowlist=None,
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.create_oauth_access_token_for_run",
        return_value="oauth-token",
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.get_sandbox_ph_mcp_configs",
        return_value=[],
    )
    mocker.patch(
        "products.tasks.backend.temporal.process_task.activities.start_agent_server.TaskRun.objects.filter"
    ).return_value.first.return_value = mocker.Mock(state={}, imported_mcp_servers=None)

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
