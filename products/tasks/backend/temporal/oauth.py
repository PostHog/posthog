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
from products.tasks.backend.models import Task

__all__ = [
    "ARRAY_APP_CLIENT_ID_DEV",
    "ARRAY_APP_CLIENT_ID_EU",
    "ARRAY_APP_CLIENT_ID_US",
    "create_oauth_access_token",
    "create_oauth_access_token_for_user",
    "create_wizard_oauth_access_token",
    "oauth_application_for_task",
]


def oauth_application_for_task(task: Task) -> SandboxOAuthApplication:
    if task.origin_product == Task.OriginProduct.POSTHOG_AI:
        return "posthog_ai"
    return "array"


def create_oauth_access_token(task: Task, *, scopes: PosthogMcpScopes = "read_only") -> str:
    """Create an OAuth access token for the task's sandbox app, scoped to the task's team.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed.
    """
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    return create_oauth_access_token_for_user(
        task.created_by,
        task.team_id,
        scopes=scopes,
        application=oauth_application_for_task(task),
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
