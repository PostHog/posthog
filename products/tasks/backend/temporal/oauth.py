from __future__ import annotations

from typing import TYPE_CHECKING, Any

from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    PosthogMcpScopes,
    SandboxOAuthApplication,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
    create_wizard_oauth_access_token_for_user as _create_wizard_oauth_access_token_for_user,
)

from products.tasks.backend.exceptions import OAuthTokenError, TaskInvalidStateError
from products.tasks.backend.logic.services.run_actor import get_task_run_credential_user, is_slack_interaction_state
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


def _oauth_application_for_task(task: Task) -> SandboxOAuthApplication:
    if task.origin_product == Task.OriginProduct.POSTHOG_AI:
        return "posthog_ai"
    return "array"


def create_oauth_access_token(
    task: Task,
    *,
    scopes: PosthogMcpScopes = "read_only",
    user: User | None = None,
    allow_task_creator_fallback: bool = True,
) -> str:
    """Create an OAuth access token for the task's sandbox app, scoped to the task's team.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed.
    """
    actor = user or (task.created_by if allow_task_creator_fallback else None)
    if not actor:
        raise TaskInvalidStateError(
            f"Task {task.id} has no user for sandbox OAuth",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing sandbox OAuth user"),
        )

    return create_oauth_access_token_for_user(
        actor,
        task.team_id,
        scopes=scopes,
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
    to mint creator credentials for a Slack run by omitting one kwarg.
    """
    actor_user = get_task_run_credential_user(task, state)
    return create_oauth_access_token(
        task,
        scopes=scopes,
        user=actor_user,
        allow_task_creator_fallback=not is_slack_interaction_state(state),
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
