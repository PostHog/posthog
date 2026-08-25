from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, get_args
from uuid import UUID

from django.db import transaction

from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    McpScopePreset,
    PosthogMcpScopes,
    SandboxOAuthApplication,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
    create_wizard_oauth_access_token_for_user as _create_wizard_oauth_access_token_for_user,
    resolve_scopes,
)

from products.mcp_store.backend.facade.api import is_builtin_agent_enforcement_enabled
from products.tasks.backend.exceptions import OAuthTokenError, TaskInvalidStateError
from products.tasks.backend.logic.services.run_actor import (
    get_task_run_credential_user,
    is_slack_interaction_state,
    loop_owner_eligible_for_credentials,
)
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, Task

if TYPE_CHECKING:
    from posthog.models.user import User

__all__ = [
    "ARRAY_APP_CLIENT_ID_DEV",
    "ARRAY_APP_CLIENT_ID_EU",
    "ARRAY_APP_CLIENT_ID_US",
    "create_oauth_access_token",
    "create_oauth_access_token_for_run",
    "create_oauth_access_token_for_user",
    "create_wizard_oauth_access_token",
]

# Loop CRUD MCP tools must never be reachable from inside a loop-fired run, regardless of the
# loop's configured connector scope (products/tasks/docs/LOOPS.md, Connectors section): a
# triggered run has no legitimate reason to create/edit/delete loops, and this closes the
# injected-instructions plant-a-persistent-loop path. loop:read stays granted.
LOOP_FIRED_RUN_EXCLUDED_SCOPES = frozenset({"loop:write"})


# Every Signals sandbox surface mints under the dedicated Signals OAuth app, so the LLM
# gateway can pin the `signals` product to that app alone. Sharing the Array app would leave
# a Signals token equally valid for `posthog_code` and `background_agents`, and the product
# is a path segment the caller picks, so any per-product budget would be self-selected.
SIGNALS_ORIGIN_PRODUCTS = frozenset(
    {
        Task.OriginProduct.SIGNAL_REPORT,
        Task.OriginProduct.SIGNALS_SCOUT,
        Task.OriginProduct.SIGNALS_CHAT,
    }
)

# Signals surfaces a person drives by hand: the Inbox report CTAs ("Create PR" / "Discuss")
# and scout chat. Scheduled scouts run under their own reserved origin and never appear here.
INTERACTIVE_SIGNALS_ORIGIN_PRODUCTS = frozenset(
    {
        Task.OriginProduct.SIGNAL_REPORT,
        Task.OriginProduct.SIGNALS_CHAT,
    }
)


def _oauth_application_for_task(task: Task) -> SandboxOAuthApplication:
    if task.origin_product == Task.OriginProduct.POSTHOG_AI:
        return "posthog_ai"
    if task.origin_product in SIGNALS_ORIGIN_PRODUCTS:
        return "signals"
    return "array"


def is_interactive_signals_run(task: Task, state: dict[str, Any] | None) -> bool:
    """Whether *this run* exists because a person pressed something, not because we scheduled it.

    Asks the run, not the task. `task.internal` is stamped once at creation and never
    recomputed, so it only ever answers for the run that created the task: Signals auto-starts
    an implementation task, and a person can later start a second run on that same task from
    the report. One task, two runs, two different initiators.

    `ai_stage` is the pipeline's own stamp on a run it started. It is absent from the task
    create serializer and sits in `_PROTECTED_RUN_STATE_KEYS`, so no caller can set or forge
    one — the review carve-outs already trust it as proof a run is self-driving. A signals run
    without one therefore cannot have come from the pipeline, which makes the interactive
    budget and its per-run ceiling the fail-closed default.
    """
    if task.origin_product not in INTERACTIVE_SIGNALS_ORIGIN_PRODUCTS:
        return False
    return not (state or {}).get("ai_stage")


def _scopes_for_loop_fired_run(scopes: PosthogMcpScopes) -> list[str]:
    resolved = resolve_scopes(scopes, include_internal_scopes=True)
    return [scope for scope in resolved if scope not in LOOP_FIRED_RUN_EXCLUDED_SCOPES]


def _workflow_run_scopes(requested: PosthogMcpScopes, state: dict[str, Any] | None) -> list[str]:
    """Scopes for a workflow-fired run: the request intersected with the run's snapshotted
    choice (neither side can widen the other), minus the automation-editing scopes loop
    runs also strip."""
    resolved = set(resolve_scopes(requested, include_internal_scopes=True))
    connectors = ((state or {}).get("config_snapshot") or {}).get("connectors")
    raw = connectors.get("posthog_mcp_scopes") if isinstance(connectors, dict) else None
    snapshot: PosthogMcpScopes | None = None
    if isinstance(raw, list):
        snapshot = [str(scope) for scope in raw]
    elif isinstance(raw, str) and raw in get_args(McpScopePreset):
        snapshot = cast(McpScopePreset, raw)
    if snapshot is not None:
        resolved &= set(resolve_scopes(snapshot, include_internal_scopes=True))
    return sorted(scope for scope in resolved if scope not in LOOP_FIRED_RUN_EXCLUDED_SCOPES)


def create_oauth_access_token(
    task: Task,
    *,
    scopes: PosthogMcpScopes = "read_only",
    user: User | None = None,
    allow_task_creator_fallback: bool = True,
    loop_id: str | None = None,
    run_state: dict[str, Any] | None = None,
) -> str:
    """Create an OAuth access token for the task's sandbox app, scoped to the task's team.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed. Pass `loop_id` for a
    loop-fired run so `loop:write` is stripped from the granted scopes regardless of `scopes`.
    Pass `run_state` so the Signals budget is picked from the run's own provenance
    (`is_interactive_signals_run`); omitting it bills a signals run as interactive, which is
    the safe default but is never what a pipeline run wants.
    """
    actor = user or (task.created_by if allow_task_creator_fallback else None)
    if not actor:
        raise TaskInvalidStateError(
            f"Task {task.id} has no user for sandbox OAuth",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing sandbox OAuth user"),
        )

    effective_scopes: PosthogMcpScopes = _scopes_for_loop_fired_run(scopes) if loop_id else scopes
    token_options: dict[str, Any] = {
        "scopes": effective_scopes,
        "application": _oauth_application_for_task(task),
        "sandbox_task_id": task.id,
    }
    if task.origin_product in {
        Task.OriginProduct.SIGNALS_SCOUT,
        Task.OriginProduct.SUPPORT_REPLY,
    } and is_builtin_agent_enforcement_enabled(task.team_id):
        # This scope only removes access to the human MCP Store surface. Add it
        # even when a legacy task lacks trusted provenance so an old spoofed
        # origin fails closed instead of inheriting its creator's connections.
        # Keyed to the same rollout flag as the Store facade: a legacy-resolved
        # task needs a member-capable token, or every member-proxy call it was
        # just granted would 403.
        token_options["include_mcp_builtin_agent_scope"] = True
    if is_interactive_signals_run(task, run_state):
        token_options["include_interactive_run_scope"] = True
    return create_oauth_access_token_for_user(actor, task.team_id, **token_options)


def create_oauth_access_token_for_run(
    task: Task,
    state: dict[str, Any] | None,
    *,
    scopes: PosthogMcpScopes = "read_only",
) -> str:
    """Mint the sandbox OAuth token for a run, resolving the acting user from run state.

    Single entry point for the run credential policy: Slack runs fail closed when their
    recorded actor can't be validated (never falling back to the task creator), while
    other runs keep the creator fallback. Callers must not re-derive this pairing by
    hand — passing ``user``/``allow_task_creator_fallback`` separately makes it possible
    to mint creator credentials for a Slack run by omitting one kwarg. Loop-fired runs
    (``loop_id`` in run state) get ``loop:write`` stripped from the granted scopes here.
    """
    with transaction.atomic():
        locked_task = (
            Task.objects.select_for_update(of=("self",))
            .select_related("created_by", "team")
            .get(id=task.id, team_id=task.team_id)
        )
        run_ownership_version = (state or {}).get(TASK_OWNERSHIP_VERSION_STATE_KEY)
        if run_ownership_version != locked_task.ownership_version:
            raise TaskInvalidStateError(
                f"Task run for {task.id} belongs to a previous task owner",
                {"task_id": task.id},
                cause=RuntimeError("task run ownership version is stale"),
            )

        actor_user = get_task_run_credential_user(locked_task, state)
        loop_id = (state or {}).get("loop_id")
        effective_scopes = scopes
        credential_owner_kind: str | None = None
        if locked_task.origin_product == Task.OriginProduct.WORKFLOW:
            effective_scopes = _workflow_run_scopes(scopes, state)
            credential_owner_kind = "workflow"
        elif loop_id is not None:
            credential_owner_kind = "loop"

        if credential_owner_kind is not None:
            credential_owner_id = actor_user.id if actor_user is not None else locked_task.created_by_id
            if not loop_owner_eligible_for_credentials(credential_owner_id, locked_task.team):
                raise TaskInvalidStateError(
                    f"{credential_owner_kind.capitalize()} task {locked_task.id} credential owner can no longer access its team",
                    {"task_id": locked_task.id},
                    cause=RuntimeError(f"{credential_owner_kind} credential owner is not an active team member"),
                )

        return create_oauth_access_token(
            locked_task,
            scopes=effective_scopes,
            user=actor_user,
            allow_task_creator_fallback=not is_slack_interaction_state(state),
            loop_id=loop_id if isinstance(loop_id, str) else None,
            run_state=state,
        )


def create_wizard_oauth_access_token(task: Task) -> str:
    """Create the OAuth access token the setup wizard uses inside a cloud wizard run.

    Minted under the wizard's own OAuthApplication with the wizard's scopes — kept separate from
    the sandbox/agent token (`create_oauth_access_token`) so the two scope sets stay independent.
    """
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    try:
        return _create_wizard_oauth_access_token_for_user(task.created_by, task.team_id)
    except RuntimeError as err:
        raise OAuthTokenError(str(err), {"team_id": task.team_id}, cause=err) from err


def create_oauth_access_token_for_user(
    user,
    team_id: int,
    *,
    scopes: PosthogMcpScopes = "read_only",
    application: SandboxOAuthApplication = "array",
    include_mcp_builtin_agent_scope: bool = False,
    include_interactive_run_scope: bool = False,
    sandbox_task_id: UUID | None = None,
) -> str:
    """Create an OAuth access token for a sandbox app, scoped to a specific team."""
    try:
        token_options: dict[str, Any] = {
            "scopes": scopes,
            "application": application,
            "sandbox_task_id": sandbox_task_id,
        }
        if include_mcp_builtin_agent_scope:
            token_options["include_mcp_builtin_agent_scope"] = True
        if include_interactive_run_scope:
            token_options["include_interactive_run_scope"] = True
        return _create_oauth_access_token_for_user(user, team_id, **token_options)
    except RuntimeError as err:
        raise OAuthTokenError(str(err), {"team_id": team_id}, cause=err) from err
