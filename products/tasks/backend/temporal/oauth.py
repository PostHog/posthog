from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.db import transaction

from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    PosthogMcpScopes,
    SandboxOAuthApplication,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
    create_wizard_oauth_access_token_for_user as _create_wizard_oauth_access_token_for_user,
    resolve_scopes,
)

from products.tasks.backend.exceptions import OAuthTokenError, TaskInvalidStateError
from products.tasks.backend.logic.services.run_actor import (
    get_task_run_credential_user,
    is_slack_interaction_state,
    loop_owner_eligible_for_credentials,
)
from products.tasks.backend.models import Task

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


def _oauth_application_for_task(task: Task) -> SandboxOAuthApplication:
    if task.origin_product == Task.OriginProduct.POSTHOG_AI:
        return "posthog_ai"
    return "array"


def _scopes_for_loop_fired_run(scopes: PosthogMcpScopes) -> list[str]:
    resolved = resolve_scopes(scopes, include_internal_scopes=True)
    return [scope for scope in resolved if scope not in LOOP_FIRED_RUN_EXCLUDED_SCOPES]


def create_oauth_access_token(
    task: Task,
    *,
    scopes: PosthogMcpScopes = "read_only",
    user: User | None = None,
    allow_task_creator_fallback: bool = True,
    loop_id: str | None = None,
) -> str:
    """Create an OAuth access token for the task's sandbox app, scoped to the task's team.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed. Pass `loop_id` for a
    loop-fired run so `loop:write` is stripped from the granted scopes regardless of `scopes`.
    """
    actor = user or (task.created_by if allow_task_creator_fallback else None)
    if not actor:
        raise TaskInvalidStateError(
            f"Task {task.id} has no user for sandbox OAuth",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing sandbox OAuth user"),
        )

    effective_scopes: PosthogMcpScopes = _scopes_for_loop_fired_run(scopes) if loop_id else scopes
    return create_oauth_access_token_for_user(
        actor,
        task.team_id,
        scopes=effective_scopes,
        application=_oauth_application_for_task(task),
    )


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
    actor_user = get_task_run_credential_user(task, state)
    loop_id = (state or {}).get("loop_id")
    if loop_id is None:
        return create_oauth_access_token(
            task,
            scopes=scopes,
            user=actor_user,
            allow_task_creator_fallback=not is_slack_interaction_state(state),
            loop_id=None,
        )

    # Loop run: re-verify the credential owner is eligible at mint time, not just at dispatch, and do
    # it atomically. `is_active` on the already-loaded `task.created_by` is stale, so the check reads
    # and locks the owner row (and its membership) freshly, then mints inside the same transaction —
    # a deactivation or membership removal can't commit between the check and token creation, and the
    # async loop cancellation can't revoke a token already handed to the sandbox.
    credential_owner_id = actor_user.id if actor_user is not None else task.created_by_id
    with transaction.atomic():
        if not loop_owner_eligible_for_credentials(credential_owner_id, task.team):
            raise TaskInvalidStateError(
                f"Loop task {task.id} credential owner can no longer access its team",
                {"task_id": task.id},
                cause=RuntimeError("loop credential owner is not an active team member"),
            )
        return create_oauth_access_token(
            task,
            scopes=scopes,
            user=actor_user,
            allow_task_creator_fallback=not is_slack_interaction_state(state),
            loop_id=loop_id if isinstance(loop_id, str) else None,
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
) -> str:
    """Create an OAuth access token for a sandbox app, scoped to a specific team."""
    try:
        return _create_oauth_access_token_for_user(user, team_id, scopes=scopes, application=application)
    except RuntimeError as err:
        raise OAuthTokenError(str(err), {"team_id": team_id}, cause=err) from err
