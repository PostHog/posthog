from collections.abc import Collection
from datetime import timedelta

from django.utils import timezone

from posthog.api.oauth.cimd import CIMDFetchError, CIMDValidationError, get_or_create_cimd_application
from posthog.models import OAuthAccessToken, OAuthApplication, User
from posthog.models.utils import generate_random_oauth_access_token
from posthog.scopes import effective_ceiling, scopes_outside_ceiling
from posthog.temporal.oauth import WEBMCP_APP_CLIENT_ID

from ..facade.contracts import McpScopesUnavailable, McpServerError

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
        try:
            return cls(get_or_create_cimd_application(WEBMCP_APP_CLIENT_ID))
        except (CIMDFetchError, CIMDValidationError) as error:
            raise McpServerError("Could not load the WebMCP client metadata") from error

    def get_or_mint(self, user: User, team_id: int, scopes: Collection[str] | None = None) -> str:
        """A live token for the user and team. `scopes` narrows the token below the app's ceiling;
        None grants the whole ceiling."""
        scope = self._scope(scopes)
        # Reuse keeps one token row per user, team and scope set per hour, rather than one per tool call.
        # The scope must match exactly, so a narrow token never serves a wider caller or the reverse.
        existing = (
            OAuthAccessToken.objects.filter(
                user=user,
                application=self._application,
                scope=scope,
                scoped_teams=[team_id],
                impersonated_by__isnull=True,
                expires__gt=timezone.now() + TOKEN_REUSE_MARGIN,
            )
            .order_by("-expires")
            .values_list("token", flat=True)
            .first()
        )
        return existing or self._mint(user, team_id, scope)

    def mint(self, user: User, team_id: int, scopes: Collection[str] | None = None) -> str:
        return self._mint(user, team_id, self._scope(scopes))

    def _scope(self, scopes: Collection[str] | None) -> str:
        if scopes is None:
            # The CIMD document on posthog.com sets what WebMCP can reach, with no deploy here.
            return " ".join(sorted(effective_ceiling(self._application.ceiling_scopes)))
        missing = scopes_outside_ceiling(scopes, self._application.ceiling_scopes)
        if missing:
            raise McpScopesUnavailable(missing)
        return " ".join(sorted(set(scopes)))

    def _mint(self, user: User, team_id: int, scope: str) -> str:
        token = generate_random_oauth_access_token(None)
        OAuthAccessToken.objects.create(
            user=user,
            application=self._application,
            token=token,
            expires=timezone.now() + TOKEN_LIFETIME,
            scope=scope,
            scoped_teams=[team_id],
        )
        return token
