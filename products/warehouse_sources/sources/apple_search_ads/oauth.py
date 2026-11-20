"""Bearer tokens for the Apple Ads service provider OAuth path.

The customer grants PostHog access from the connect form, and the grant is stored as an
`apple-ads` integration. Apple's access tokens live one hour, which a backfill routinely outlives,
so the token is resolved per authentication rather than once per run.
"""

from products.warehouse_sources.sources.apple_search_ads.apple_search_ads import AppleSearchAdsAuthError
from products.warehouse_sources.sources.sdk import IntegrationRecord, OauthIntegration

# Both are matched by `get_non_retryable_errors`, so keep the wording in step with the source.
TOKEN_REFRESH_FAILED_MESSAGE = "Failed to refresh the Apple Ads connection. Please reconnect your Apple Ads account."
MISSING_TOKEN_MESSAGE = "The connected Apple Ads account has no access token. Please reconnect it."


class AppleAdsOauthError(AppleSearchAdsAuthError):
    """Raised where the client expects an auth failure, so `validate_credentials` reports it."""


def apple_ads_access_token(integration: IntegrationRecord) -> str:
    """Current bearer token for an Apple Ads grant, refreshing it when it has expired."""
    oauth_integration = OauthIntegration(integration)
    if oauth_integration.access_token_expired():
        integration = oauth_integration.refresh_access_token()
        # `refresh_terminal`, not `integration.errors`, because a failed refresh also sets
        # `errors` for a transient provider hiccup (network error, 429, 5xx) that a later
        # attempt clears on its own. `refresh_terminal` only latches once the grant itself is
        # confirmed dead (an unreadable secret, or an unbroken streak of `invalid_grant`
        # responses), which is the one condition only a reconnect can fix. Until then, fall
        # through and keep using the still-valid access token the conservative expiry check
        # refreshed early for.
        if integration.config.get("refresh_terminal"):
            raise AppleAdsOauthError(TOKEN_REFRESH_FAILED_MESSAGE)

    if not integration.access_token:
        raise AppleAdsOauthError(MISSING_TOKEN_MESSAGE)
    return integration.access_token
