from __future__ import annotations

from typing import TYPE_CHECKING

from posthog.temporal.oauth import (
    ARRAY_APP_CLIENT_ID_DEV,
    ARRAY_APP_CLIENT_ID_EU,
    ARRAY_APP_CLIENT_ID_US,
    PosthogMcpScopes,
    SandboxOAuthApplication,
    create_oauth_access_token_for_user as _create_oauth_access_token_for_user,
)

from products.tasks.backend.exceptions import OAuthTokenError, TaskInvalidStateError
from products.tasks.backend.models import Task

if TYPE_CHECKING:
    from posthog.models.user import User

__all__ = [
    "ARRAY_APP_CLIENT_ID_DEV",
    "ARRAY_APP_CLIENT_ID_EU",
    "ARRAY_APP_CLIENT_ID_US",
    "create_oauth_access_token",
    "create_oauth_access_token_for_user",
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
