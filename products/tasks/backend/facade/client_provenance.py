from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.oauth_provenance import is_interactive_desktop_grant
from posthog.temporal.oauth import SANDBOX_OAUTH_APP_CLIENT_IDS

from products.tasks.backend.models import TaskClientProvenance


def is_sandbox_oauth_request(request: Request) -> bool:
    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return False
    token = authenticator.access_token
    return (
        token.application is not None
        and token.application.client_id in SANDBOX_OAUTH_APP_CLIENT_IDS
        and (token.sandbox_task_id is not None or "internal_run:read" in (token.scope or "").split())
    )


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    if is_interactive_desktop_grant(request):
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None
