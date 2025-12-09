from datetime import timedelta

from django.utils import timezone

from posthog.models import OAuthAccessToken, OAuthApplication
from posthog.models.utils import generate_random_oauth_access_token
from posthog.utils import get_instance_region

from products.tasks.backend.models import Task
from products.tasks.backend.temporal.exceptions import OAuthTokenError, TaskInvalidStateError

ARRAY_APP_CLIENT_ID_US = "HCWoE0aRFMYxIxFNTTwkOORn5LBjOt2GVDzwSw5W"
ARRAY_APP_CLIENT_ID_EU = "AIvijgMS0dxKEmr5z6odvRd8Pkh5vts3nPTzgzU9"
ARRAY_APP_CLIENT_ID_DEV = "DC5uRLVbGI02YQ82grxgnK6Qn12SXWpCqdPb60oZ"


def get_array_app() -> OAuthApplication:
    region = get_instance_region()
    if region == "EU":
        client_id = ARRAY_APP_CLIENT_ID_EU
    elif region == "US":
        client_id = ARRAY_APP_CLIENT_ID_US
    else:
        client_id = ARRAY_APP_CLIENT_ID_DEV

    try:
        return OAuthApplication.objects.get(client_id=client_id)
    except OAuthApplication.DoesNotExist:
        raise OAuthTokenError(
            f"Array app not found for region {region}",
            {"region": region, "client_id": client_id},
            cause=RuntimeError(f"No OAuthApplication with client_id={client_id}"),
        )


def get_default_scopes() -> list[str]:
    return [
        "error_tracking:read",
        "user:read",
        "organization:read",
        "project:read",
        "task:write",
    ]


def create_oauth_access_token(task: Task) -> str:
    """Create an OAuth access token for the Array app, scoped to the task's team.

    OAuth tokens auto-expire after 1 hour, so no cleanup is needed.
    """
    if not task.created_by:
        raise TaskInvalidStateError(
            f"Task {task.id} has no created_by user",
            {"task_id": task.id},
            cause=RuntimeError(f"Task {task.id} missing created_by field"),
        )

    return create_oauth_access_token_for_user(task.created_by, task.team_id)


def create_oauth_access_token_for_user(user, team_id: int) -> str:
    """Create an OAuth access token for the Array app, scoped to a specific team.

    OAuth tokens auto-expire after 1 hour, so no cleanup is needed.
    """
    scopes = get_default_scopes()
    app = get_array_app()
    token_value = generate_random_oauth_access_token(None)

    OAuthAccessToken.objects.create(
        user=user,
        application=app,
        token=token_value,
        expires=timezone.now() + timedelta(hours=1),
        scope=" ".join(scopes),
        scoped_teams=[team_id],
    )

    return token_value
