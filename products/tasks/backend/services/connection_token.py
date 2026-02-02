from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from posthog.jwt import PosthogJwtAudience, encode_jwt

if TYPE_CHECKING:
    from products.tasks.backend.models import TaskRun


def create_sandbox_connection_token(task_run: TaskRun, user_id: int, distinct_id: str) -> str:
    """
    Create a JWT connection token for direct sandbox connections.

    The token contains all information the sandbox needs to authenticate
    the connection without calling back to Django.

    Args:
        task_run: The TaskRun to create a token for
        user_id: The user ID making the connection
        distinct_id: The user's distinct_id for analytics

    Returns:
        A signed JWT token valid for 24 hours
    """
    payload = {
        "run_id": str(task_run.id),
        "task_id": str(task_run.task_id),
        "team_id": task_run.team_id,
        "user_id": user_id,
        "distinct_id": distinct_id,
    }

    return encode_jwt(
        payload=payload,
        expiry_delta=timedelta(hours=24),
        audience=PosthogJwtAudience.SANDBOX_CONNECTION,
    )
