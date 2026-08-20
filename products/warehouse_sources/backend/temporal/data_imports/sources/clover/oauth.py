from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.clover.settings import (
    CLOVER_INTEGRATION_KIND_REGIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Clover access tokens live ~30m. Re-mint through the DB well before that so a token never expires
# mid-request; the DB refresh only actually spends the refresh token once the row is past its own
# half-life threshold, so this cadence just decides how often we re-check the row.
_CLOVER_TOKEN_REFRESH_AFTER = timedelta(minutes=10)


def resolve_clover_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid Clover OAuth access token, refreshing under a row lock when needed.

    Clover access tokens are short-lived (~30m) and its refresh tokens are single-use: each refresh
    returns a new pair and immediately invalidates the one just spent. So a refresh MUST (a) persist
    the newly rotated refresh token — ``refresh_access_token`` does — and (b) be serialized against
    the parallel schema syncs that share one integration. ``select_for_update`` gives us that
    Postgres row lock, and we reload inside it so a sync that lost the race picks up the token
    another already rotated instead of re-spending the old one.

    ``current_token`` is the token the caller last used; when it still matches the row (nobody else
    rotated past it) we refresh, otherwise we hand back the fresher token already on the row.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(
            id=integration_id, team_id=team_id, kind__in=CLOVER_INTEGRATION_KIND_REGIONS
        )
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Clover access token not found")
    return token


class CloverIntegrationAuth(AuthConfigBase):
    """Bearer auth for the Clover OAuth path that re-mints through the integration row.

    Clover rotates its single-use refresh token on every refresh, so the token can only be re-minted
    where the rotation is persisted — the DB row, under a lock (see :func:`resolve_clover_oauth_token`).
    The framework's in-process ``OAuth2Auth`` mint can't persist that rotation, so this auth does the
    refresh through the row instead: it caches a token for ~10m, then re-resolves. Because it
    refreshes *before* the ~30m expiry, a sync never sees a mid-flight 401 from an expired token — so
    the source can keep treating 401 as a non-retryable bad-credential signal for both auth methods.
    """

    def __init__(self, integration_id: int, team_id: int, access_token: str) -> None:
        self._integration_id = integration_id
        self._team_id = team_id
        self.token: str = access_token
        self._refresh_after: datetime = datetime.now(UTC) + _CLOVER_TOKEN_REFRESH_AFTER

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if datetime.now(UTC) >= self._refresh_after:
            self.token = resolve_clover_oauth_token(self._integration_id, self._team_id, self.token)
            self._refresh_after = datetime.now(UTC) + _CLOVER_TOKEN_REFRESH_AFTER
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()
