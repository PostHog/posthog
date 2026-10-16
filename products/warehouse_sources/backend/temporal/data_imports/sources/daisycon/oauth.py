from datetime import UTC, datetime, timedelta

from django.db import transaction

from requests import PreparedRequest

from posthog.models.integration import Integration, OauthIntegration

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import AuthConfigBase

# Daisycon access tokens live 30 minutes, and the resolver refreshes any token past half its life, so a
# resolved token has at least 15 minutes left. Rechecking every 10 minutes never sends an expired one.
_DAISYCON_TOKEN_RECHECK_AFTER = timedelta(minutes=10)

DAISYCON_GRANT_REVOKED_ERROR = "Daisycon no longer accepts the stored authorization"


class DaisyconTokenRefreshError(Exception):
    """A refresh failed for a reason that can clear, such as a timeout or a 5xx from Daisycon."""


def resolve_daisycon_oauth_token(integration_id: int, team_id: int) -> str:
    """Return a Daisycon access token with at least half its lifetime left, refreshing under a row lock.

    Daisycon refresh tokens are single-use and rotate on every refresh. Parallel schema syncs share one
    integration, so the refresh is serialized with `select_for_update`, and the row is reloaded inside
    the lock: a sync that lost the race picks up the token another sync already rotated instead of
    spending the old refresh token again. `refresh_access_token` persists the rotation.
    """
    with transaction.atomic():
        integration = Integration.objects.select_for_update().get(id=integration_id, team_id=team_id, kind="daisycon")
        oauth = OauthIntegration(integration)
        if oauth.access_token_expired():
            oauth.refresh_access_token()
        # A failed refresh records the failure and returns, leaving the old token on the row. The error is
        # raised after the block, so the failure count that leads to the terminal state is committed.
        refresh_failed = oauth.access_token_expired()
        grant_revoked = bool(integration.config.get("refresh_terminal"))
        token = integration.access_token

    if refresh_failed:
        if grant_revoked:
            raise ValueError(f"{DAISYCON_GRANT_REVOKED_ERROR}. Reconnect your Daisycon account.")
        raise DaisyconTokenRefreshError("Daisycon did not refresh the access token")

    if not token:
        raise ValueError("Daisycon access token not found")
    return token


class DaisyconIntegrationAuth(AuthConfigBase):
    """Bearer auth that rechecks the Daisycon access token through the integration row.

    The framework's in-process `OAuth2Auth` cannot persist a rotated refresh token, so the refresh
    goes through the row instead (see `resolve_daisycon_oauth_token`). Rechecking before the token can
    expire means a long sync never sees a 401 from an expired token, so a 401 stays a reliable sign
    that the grant itself is gone.
    """

    def __init__(self, integration_id: int, team_id: int, access_token: str) -> None:
        self._integration_id = integration_id
        self._team_id = team_id
        self.token: str = access_token
        self._recheck_after: datetime = datetime.now(UTC) + _DAISYCON_TOKEN_RECHECK_AFTER

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        if datetime.now(UTC) >= self._recheck_after:
            self.token = resolve_daisycon_oauth_token(self._integration_id, self._team_id)
            self._recheck_after = datetime.now(UTC) + _DAISYCON_TOKEN_RECHECK_AFTER
        request.headers["Authorization"] = f"Bearer {self.token}"
        return request

    def secret_values(self) -> tuple[str, ...]:
        return (self.token,) if self.token else ()
