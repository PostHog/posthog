from posthog.models.user import User
from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    PosthogMcpScopes,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
)

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.temporal.exceptions import OAuthTokenError, TaskInvalidStateError

__all__ = [
    "ARRAY_APP_CLIENT_ID_DEV",
    "ARRAY_APP_CLIENT_ID_EU",
    "ARRAY_APP_CLIENT_ID_US",
    "create_oauth_access_token_for_run",
    "create_oauth_access_token_for_user",
    "resolve_run_initiator",
]


def resolve_run_initiator(task_run: TaskRun, task: Task | None = None) -> User:
    """Return the user whose identity should be used to execute this run.

    The OAuth token, MCP installations, and private sandbox environments all
    follow this identity. Prefer the user who initiated the run; fall back to
    the task creator only for legacy runs created before the run initiator was
    tracked. Raises if neither is available.
    """
    initiator = task_run.created_by
    if initiator is not None:
        return initiator
    fallback_task = task if task is not None else task_run.task
    if fallback_task.created_by is not None:
        return fallback_task.created_by
    raise TaskInvalidStateError(
        f"Task run {task_run.id} has no initiator and task {fallback_task.id} has no created_by user",
        {"task_id": str(fallback_task.id), "run_id": str(task_run.id)},
        cause=RuntimeError(f"Task run {task_run.id} missing initiator"),
    )


def create_oauth_access_token_for_run(
    task_run: TaskRun,
    *,
    task: Task | None = None,
    scopes: PosthogMcpScopes = "read_only",
) -> str:
    """Mint an OAuth access token for the user who initiated this run.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed.
    """
    user = resolve_run_initiator(task_run, task=task)
    return create_oauth_access_token_for_user(user, task_run.team_id, scopes=scopes)


def create_oauth_access_token_for_user(user, team_id: int, *, scopes: PosthogMcpScopes = "read_only") -> str:
    """Create an OAuth access token for the Array app, scoped to a specific team."""
    try:
        return _create_oauth_access_token_for_user(user, team_id, scopes=scopes)
    except RuntimeError as err:
        raise OAuthTokenError(str(err), {"team_id": team_id}, cause=err) from err
