from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from posthog.api.oauth.cimd import get_or_create_cimd_application
from posthog.models import OAuthAccessToken, OAuthApplication, User
from posthog.models.utils import generate_random_oauth_access_token
from posthog.scopes import effective_ceiling

TOKEN_LIFETIME = timedelta(hours=1)
# A token this close to expiry is not reused, so a slow tool call cannot outlive it.
TOKEN_REUSE_MARGIN = timedelta(minutes=10)


class WebMCPTokenIssuer:
    """Issues the MCP access tokens that stand in for a browser session.

    The MCP server authenticates bearer tokens only, and the session cookie never leaves the app
    origin, so the proxy exchanges the session for a short-lived token scoped to one team.
    """

    def __init__(self, application: OAuthApplication) -> None:
        self._application = application

    @classmethod
    def for_instance(cls) -> "WebMCPTokenIssuer":
        return cls(get_or_create_cimd_application(settings.WEBMCP_OAUTH_CLIENT_ID))

    def get_or_mint(self, user: User, team_id: int) -> str:
        # Reuse keeps one token row per user and team per hour, rather than one per tool call.
        existing = (
            OAuthAccessToken.objects.filter(
                user=user,
                application=self._application,
                scoped_teams=[team_id],
                impersonated_by__isnull=True,
                expires__gt=timezone.now() + TOKEN_REUSE_MARGIN,
            )
            .order_by("-expires")
            .values_list("token", flat=True)
            .first()
        )
        return existing or self.mint(user, team_id)

    def mint(self, user: User, team_id: int) -> str:
        token = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            user=user,
            application=self._application,
            token=token,
            expires=timezone.now() + TOKEN_LIFETIME,
            # The CIMD document on posthog.com sets what WebMCP can reach, with no deploy here.
            scope=" ".join(sorted(effective_ceiling(self._application.ceiling_scopes))),
            scoped_teams=[team_id],
        )
        return token
