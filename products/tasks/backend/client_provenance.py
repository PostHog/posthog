from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.temporal.oauth import POSTHOG_DESKTOP_OAUTH_CLIENT_IDS

from products.tasks.backend.models import TaskClientProvenance


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return None

    access_token = getattr(authenticator, "access_token", None)
    application = getattr(access_token, "application", None)
    scopes = set((getattr(access_token, "scope", "") or "").split())
    if application is None or "internal_run:read" in scopes:
        return None
    if application.client_id in POSTHOG_DESKTOP_OAUTH_CLIENT_IDS:
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None
