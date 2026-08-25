import pytest
from unittest.mock import MagicMock, patch

from posthog.models import Organization, Team
from posthog.models.user import User
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.exceptions import TaskInvalidStateError
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, MCPBuiltInAgentKey, Task
from products.tasks.backend.temporal.oauth import create_oauth_access_token, create_oauth_access_token_for_run


@pytest.mark.parametrize(
    ("origin_product", "application"),
    [
        (Task.OriginProduct.SIGNALS_SCOUT, "signals"),
        (Task.OriginProduct.SUPPORT_REPLY, "array"),
    ],
)
@patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=True)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_built_in_agent_origins_use_restricted_oauth_scope(
    mock_create: MagicMock,
    mock_enforcement: MagicMock,
    origin_product: Task.OriginProduct,
    application: str,
) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=origin_product,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application=application,
        sandbox_task_id=task.id,
        include_mcp_builtin_agent_scope=True,
    )


@patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=True)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_posthog_ai_task_keeps_member_token_and_posthog_ai_oauth_application(
    mock_create: MagicMock,
    mock_enforcement: MagicMock,
) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.POSTHOG_AI,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="posthog_ai",
        sandbox_task_id=task.id,
    )


@patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=False)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_built_in_agent_origin_keeps_member_token_until_gateway_flag_rollout(
    mock_create: MagicMock,
    mock_enforcement: MagicMock,
) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.SUPPORT_REPLY,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="array",
        sandbox_task_id=task.id,
    )


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_default_task_uses_array_oauth_application(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    assert create_oauth_access_token(task) == "token"

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes="read_only",
        application="array",
        sandbox_task_id=task.id,
    )


@pytest.mark.parametrize(
    ("origin_product", "internal", "run_state", "application", "interactive"),
    [
        # Inbox CTA: a person creates the task, so no pipeline stage is ever stamped.
        (Task.OriginProduct.SIGNAL_REPORT, False, None, "signals", True),
        # Auto-started implementation: the pipeline stamps the run it started.
        (Task.OriginProduct.SIGNAL_REPORT, True, {"ai_stage": "implementation"}, "signals", False),
        # A person starting a second run on that same auto-started task. `internal` still says
        # True because it answers for the task, but this run carries no stage of its own.
        (Task.OriginProduct.SIGNAL_REPORT, True, {"mode": "interactive"}, "signals", True),
        # A forged stage is impossible through the API, but an empty string must not read as one.
        (Task.OriginProduct.SIGNAL_REPORT, True, {"ai_stage": ""}, "signals", True),
        (Task.OriginProduct.SIGNAL_REPORT, True, {"ai_stage": "research"}, "signals", False),
        (Task.OriginProduct.SIGNAL_REPORT, True, {"ai_stage": "custom_agent"}, "signals", False),
        (Task.OriginProduct.SIGNALS_CHAT, False, None, "signals", True),
        (Task.OriginProduct.SIGNALS_SCOUT, True, {"ai_stage": "scout"}, "signals", False),
        (Task.OriginProduct.USER_CREATED, False, None, "array", False),
    ],
)
@patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=False)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_signals_origins_mint_under_the_signals_app_and_mark_only_user_started_runs(
    mock_create: MagicMock,
    mock_enforcement: MagicMock,
    origin_product: Task.OriginProduct,
    internal: bool,
    run_state: dict | None,
    application: str,
    interactive: bool,
) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=origin_product,
        internal=internal,
    )

    assert create_oauth_access_token(task, run_state=run_state) == "token"

    expected: dict = {
        "scopes": "read_only",
        "application": application,
        "sandbox_task_id": task.id,
    }
    if interactive:
        expected["include_interactive_run_scope"] = True
    mock_create.assert_called_once_with(task.created_by, 123, **expected)


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth.is_builtin_agent_enforcement_enabled", return_value=False)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_two_runs_on_one_auto_started_task_get_different_signals_budgets(
    mock_create: MagicMock,
    mock_enforcement: MagicMock,
) -> None:
    organization = Organization.objects.create(name="signals-budget-org")
    team = Team.objects.create(organization=organization, name="signals-budget-team")
    creator = User.objects.create(email="signals-budget-creator@example.com")
    task = Task.objects.create(
        team=team,
        title="Implementation: report",
        created_by=creator,
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
        internal=True,
    )

    create_oauth_access_token_for_run(task, {"ai_stage": "implementation", "mode": "background"})
    assert "include_interactive_run_scope" not in mock_create.call_args.kwargs

    create_oauth_access_token_for_run(task, {"mode": "interactive"})
    assert mock_create.call_args.kwargs["include_interactive_run_scope"] is True


def test_oauth_token_can_disable_task_creator_fallback() -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token(task, user=None, allow_task_creator_fallback=False)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("origin_product", "agent_key"),
    [
        (Task.OriginProduct.SIGNALS_SCOUT, "scout"),
        (Task.OriginProduct.SUPPORT_REPLY, "support"),
    ],
)
def test_server_created_task_persists_trusted_mcp_agent_marker(
    origin_product: Task.OriginProduct, agent_key: MCPBuiltInAgentKey
) -> None:
    organization = Organization.objects.create(name=f"agent-marker-{agent_key}")
    team = Team.objects.create(organization=organization, name="agent-marker-team")
    creator = User.objects.create(email=f"agent-marker-{agent_key}@example.com")
    owner = User.objects.create(email=f"agent-owner-{agent_key}@example.com")

    task = Task.create_without_run(
        team=team,
        title="Agent task",
        description="Run the agent",
        origin_product=origin_product,
        user_id=creator.id,
        mcp_builtin_agent_key=agent_key,
        mcp_credential_owner_id=owner.id,
    )

    assert task.state == {"mcp_builtin_agent_key": agent_key, "mcp_credential_owner_id": owner.id}
    assert task.mcp_builtin_agent_key == agent_key
    # The credential owner is its own value, not the task's creator: the run acts as `creator`
    # but may only mount `owner`'s MCP grants.
    assert task.mcp_credential_owner_id == owner.id


@pytest.mark.django_db
def test_reserved_origin_without_matching_server_marker_is_untrusted() -> None:
    organization = Organization.objects.create(name="legacy-agent-marker")
    team = Team.objects.create(organization=organization, name="legacy-agent-marker-team")
    creator = User.objects.create(email="legacy-agent-marker@example.com")
    legacy_task = Task.objects.create(
        team=team,
        created_by=creator,
        title="Legacy",
        description="Untrusted origin",
        origin_product=Task.OriginProduct.SUPPORT_REPLY,
        state={"mcp_credential_owner_id": creator.id},
    )

    assert legacy_task.mcp_builtin_agent_key is None
    # An owner id without the server-stamped agent marker resolves to nothing, so an
    # untrusted task can never borrow that person's grants.
    assert legacy_task.mcp_credential_owner_id is None

    unstamped = Task.create_without_run(
        team=team,
        title="Unstamped",
        description="No agent marker",
        origin_product=Task.OriginProduct.USER_CREATED,
        user_id=creator.id,
        mcp_credential_owner_id=creator.id,
    )
    assert unstamped.state == {}
    assert unstamped.mcp_credential_owner_id is None

    with pytest.raises(ValueError, match="does not match task origin"):
        Task.create_without_run(
            team=team,
            title="Mismatch",
            description="Mismatched marker",
            origin_product=Task.OriginProduct.SUPPORT_REPLY,
            user_id=creator.id,
            mcp_builtin_agent_key="scout",
        )


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_run_token_fails_closed_for_slack_run_with_unresolvable_actor(mock_create: MagicMock) -> None:
    organization = Organization.objects.create(name="oauth-run-org")
    team = Team.objects.create(organization=organization, name="oauth-run-team")
    creator = User.objects.create(email="oauth-run-creator@example.com")
    task = Task.objects.create(
        team=team,
        title="Investigate thread",
        created_by=creator,
        origin_product=Task.OriginProduct.SLACK,
    )
    state = {"interaction_origin": "slack", "slack_actor_user_id": creator.id + 999_999}

    # A Slack run whose recorded actor can't be validated must never mint the
    # task creator's token.
    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()

    # Non-Slack runs keep the creator fallback.
    assert create_oauth_access_token_for_run(task, {}) == "token"


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_run_token_rejects_previous_task_owner(mock_create: MagicMock) -> None:
    organization = Organization.objects.create(name="oauth-handoff-org")
    team = Team.objects.create(organization=organization, name="oauth-handoff-team")
    creator = User.objects.create(email="oauth-handoff-creator@example.com")
    task = Task.objects.create(
        team=team,
        title="Transferred task",
        created_by=creator,
        state={TASK_OWNERSHIP_VERSION_STATE_KEY: "new-owner"},
    )

    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, {})

    mock_create.assert_not_called()


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_run_fails_closed_when_owner_is_not_a_current_org_member(mock_create: MagicMock) -> None:
    from posthog.models import Organization, Team
    from posthog.models.organization import OrganizationMembership
    from posthog.models.user import User

    organization = Organization.objects.create(name="loop-cred-org")
    team = Team.objects.create(organization=organization, name="loop-cred-team")
    owner = User.objects.create(email="loop-owner-cred@example.com")
    task = Task.objects.create(team=team, title="Loop run", created_by=owner, origin_product=Task.OriginProduct.LOOP)
    state = {"loop_id": "loop-1"}

    # Re-check at mint time: a just-offboarded owner (no membership) must not mint credentials for an
    # in-flight run, even though the async loop cancellation may not have landed yet.
    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()

    OrganizationMembership.objects.create(organization=organization, user=owner)
    assert create_oauth_access_token_for_run(task, state) == "token"


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_run_rechecks_owner_active_state_from_the_database(mock_create: MagicMock) -> None:
    from posthog.models import Organization, Team
    from posthog.models.organization import OrganizationMembership
    from posthog.models.user import User

    organization = Organization.objects.create(name="loop-fresh-org")
    team = Team.objects.create(organization=organization, name="loop-fresh-team")
    owner = User.objects.create(email="loop-fresh-owner@example.com")
    OrganizationMembership.objects.create(organization=organization, user=owner)
    task = Task.objects.create(team=team, title="Loop run", created_by=owner, origin_product=Task.OriginProduct.LOOP)
    state = {"loop_id": "loop-1"}

    # Deactivate directly in the DB; `task.created_by` stays cached as active. The mint must re-read
    # the row, not trust the stale in-memory `is_active`.
    User.objects.filter(id=owner.id).update(is_active=False)

    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, state)
    mock_create.assert_not_called()


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_loop_fired_run_excludes_loop_write_scope(mock_create: MagicMock) -> None:
    """A run whose state carries loop_id must never receive a loop:write-scoped token,
    regardless of the requested scopes — this is the token-layer half of the loop CRUD
    MCP block (see LOOP_FIRED_RUN_EXCLUDED_SCOPES)."""
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    create_oauth_access_token(task, scopes=["loop:read", "loop:write", "task:read"], loop_id="loop-1")

    _, kwargs = mock_create.call_args
    assert "loop:write" not in kwargs["scopes"]
    assert "loop:read" in kwargs["scopes"]
    assert "task:read" in kwargs["scopes"]


@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_non_loop_run_keeps_loop_write_scope(mock_create: MagicMock) -> None:
    task = MagicMock(
        id="task-id",
        created_by=MagicMock(),
        team_id=123,
        origin_product=Task.OriginProduct.USER_CREATED,
    )

    create_oauth_access_token(task, scopes=["loop:read", "loop:write", "task:read"], loop_id=None)

    mock_create.assert_called_once_with(
        task.created_by,
        123,
        scopes=["loop:read", "loop:write", "task:read"],
        application="array",
        sandbox_task_id=task.id,
    )


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_workflow_run_fails_closed_when_owner_is_not_a_current_org_member(mock_create: MagicMock) -> None:
    from posthog.models.organization import OrganizationMembership

    organization = Organization.objects.create(name="wf-cred-org")
    team = Team.objects.create(organization=organization, name="wf-cred-team")
    owner = User.objects.create(email="wf-owner-cred@example.com")
    task = Task.objects.create(
        team=team, title="Workflow run", created_by=owner, origin_product=Task.OriginProduct.WORKFLOW
    )

    # Same guard as loop runs: an owner offboarded after task creation must not mint
    # credentials for a later run of it.
    with pytest.raises(TaskInvalidStateError):
        create_oauth_access_token_for_run(task, {})
    mock_create.assert_not_called()

    OrganizationMembership.objects.create(organization=organization, user=owner)
    assert create_oauth_access_token_for_run(task, {}) == "token"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("requested", "snapshot"),
    [
        ("full", "read_only"),
        ("read_only", "full"),
    ],
)
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_workflow_run_scopes_never_exceed_request_or_snapshot(
    mock_create: MagicMock, requested: PosthogMcpScopes, snapshot: str
) -> None:
    from posthog.models.organization import OrganizationMembership
    from posthog.temporal.oauth import resolve_scopes

    organization = Organization.objects.create(name="wf-scope-org")
    team = Team.objects.create(organization=organization, name="wf-scope-team")
    owner = User.objects.create(email="wf-scope-owner@example.com")
    OrganizationMembership.objects.create(organization=organization, user=owner)
    task = Task.objects.create(
        team=team, title="Workflow run", created_by=owner, origin_product=Task.OriginProduct.WORKFLOW
    )
    state = {"config_snapshot": {"connectors": {"posthog_mcp_scopes": snapshot}}}

    create_oauth_access_token_for_run(task, state, scopes=requested)

    granted = set(mock_create.call_args.kwargs["scopes"])
    read_only = set(resolve_scopes("read_only", include_internal_scopes=True))
    # Whichever side is narrower wins: a teammate rerun requesting full cannot exceed the
    # workflow's snapshot, and a narrow request is never widened to the snapshot.
    assert granted <= read_only


@pytest.mark.django_db
@patch("products.tasks.backend.temporal.oauth._create_oauth_access_token_for_user", return_value="token")
def test_workflow_fired_run_excludes_loop_write_scope(mock_create: MagicMock) -> None:
    from posthog.models.organization import OrganizationMembership

    organization = Organization.objects.create(name="wf-strip-org")
    team = Team.objects.create(organization=organization, name="wf-strip-team")
    owner = User.objects.create(email="wf-strip-owner@example.com")
    OrganizationMembership.objects.create(organization=organization, user=owner)
    task = Task.objects.create(
        team=team, title="Workflow run", created_by=owner, origin_product=Task.OriginProduct.WORKFLOW
    )
    state = {"config_snapshot": {"connectors": {"posthog_mcp_scopes": "full"}}}

    create_oauth_access_token_for_run(task, state, scopes="full")

    granted = mock_create.call_args.kwargs["scopes"]
    assert "loop:write" not in granted
    assert "loop:read" in granted
