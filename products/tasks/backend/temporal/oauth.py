from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
)

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import OAuthTokenError, TaskInvalidStateError

__all__ = [
    "ARRAY_APP_CLIENT_ID_DEV",
    "ARRAY_APP_CLIENT_ID_EU",
    "ARRAY_APP_CLIENT_ID_US",
    "create_oauth_access_token",
    "create_oauth_access_token_for_user",
]


def create_oauth_access_token(task: Task) -> str:
    """Create an OAuth access token for the Array app, scoped to the task's team.

    OAuth tokens auto-expire after 6 hours, so no cleanup is needed.
    """
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    return create_oauth_access_token_for_user(task.created_by, task.team_id)


def create_oauth_access_token_for_user(user, team_id: int) -> str:
    """Create an OAuth access token for the Array app, scoped to a specific team."""
    try:
        return _create_oauth_access_token_for_user(user, team_id)
    except RuntimeError as err:
        raise OAuthTokenError(str(err), {"team_id": team_id}, cause=err) from err
