from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Resend access tokens live ~15m. Re-mint through the DB a few minutes before that so a token never
# expires mid-request; the DB refresh only actually spends the refresh token once it's past its own
# half-life threshold, so this cadence just decides how often we re-check the row.
_RESEND_TOKEN_REFRESH_AFTER = timedelta(minutes=10)


def resolve_resend_oauth_token(integration_id: int, team_id: int, current_token: str | None = None) -> str:
    """Return a valid Resend OAuth access token, refreshing under a row lock when needed.

    Resend access tokens are short-lived (~15m) and its refresh tokens rotate on every use, with
    reuse-detection that revokes the whole grant if a rotated token is dropped or spent twice. So a
    refresh MUST (a) persist the newly rotated refresh token — ``refresh_access_token`` does — and
    (b) be serialized against the parallel schema syncs that share one integration. ``select_for_update``
    gives us that Postgres row lock, and we reload inside it so a sync that lost the race picks up the
    token another already rotated instead of re-spending the old one.

    ``current_token`` is the token the caller just refreshed from; when it still matches the row
    (nobody else rotated past it) we refresh, otherwise we hand back the fresher token already on the row.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="resend")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired() or (current_token is not None and integration.access_token == current_token):
            oauth.refresh_access_token()
        token = integration.access_token

    if not token:
        raise ValueError("Resend access token not found")
    return token


class ResendIntegrationAuth(AuthConfigBase):
    """Bearer auth for the Resend OAuth path that proactively re-mints through the integration row.

    Resend rotates its single-use refresh token on every refresh, so the token can only be re-minted
    where the rotation is persisted — the DB row, under a lock (see :func:`resolve_resend_oauth_token`).
    The framework's in-process :class:`OAuth2Auth` mint can't persist that rotation, so this auth does
    the refresh through the row instead: it caches a token for ~10m, then re-resolves. Because it
    refreshes *before* the ~15m expiry, a sync never sees a mid-flight 401 from an expired token — so
    the source can keep treating 401 as a non-retryable bad-credential signal for both auth methods.
    """

    def __init__(self, integration_id: int, team_id: int, access_token: str) -> None:
        self._integration_id = integration_id
        self._team_id = team_id
        self.token: str = access_token
        self._refresh_after: datetime = datetime.now(UTC) + _RESEND_TOKEN_REFRESH_AFTER

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if datetime.now(UTC) >= self._refresh_after:
            self.token = resolve_resend_oauth_token(self._integration_id, self._team_id, self.token)
            self._refresh_after = datetime.now(UTC) + _RESEND_TOKEN_REFRESH_AFTER
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()
