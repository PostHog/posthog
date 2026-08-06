from rest_framework.request import Request

from posthog.auth import OAuthAccessTokenAuthentication
from posthog.models.oauth import OAuthRefreshToken
from posthog.temporal.oauth import POSTHOG_DESKTOP_OAUTH_CLIENT_IDS

from products.tasks.backend.models import TaskClientProvenance


def get_task_client_provenance(request: Request) -> TaskClientProvenance | None:
    authenticator = getattr(request, "successful_authenticator", None)
    if not isinstance(authenticator, OAuthAccessTokenAuthentication):
        return None

    access_token = getattr(authenticator, "access_token", None)
    application = getattr(access_token, "application", None)
    scopes = set((getattr(access_token, "scope", "") or "").split())
    if application is None or "internal_run:read" in scopes or not _has_authorization_flow_lineage(access_token):
        return None
    if application.client_id in POSTHOG_DESKTOP_OAUTH_CLIENT_IDS:
        return TaskClientProvenance.POSTHOG_DESKTOP
    return None


def _has_authorization_flow_lineage(access_token: object) -> bool:
    if getattr(access_token, "source_refresh_token_id", None) is not None:
        return True
    access_token_id = getattr(access_token, "id", None)
    if access_token_id is None:
        return False
    return OAuthRefreshToken.objects.filter(access_token_id=access_token_id).exists()
