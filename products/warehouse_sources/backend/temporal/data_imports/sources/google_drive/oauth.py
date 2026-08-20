from posthog.models.integration import Integration, OauthIntegration

GOOGLE_DRIVE_INTEGRATION_KIND = "google-drive"

MISSING_INTEGRATION_ID_ERROR = "Missing Google Drive integration ID"
MISSING_ACCESS_TOKEN_ERROR = "Google Drive access token not found"

# Google access tokens live an hour. Re-reading the row well inside that window keeps a long page
# walk on a fresh token and picks up a refresh another worker already persisted.
INTEGRATION_TOKEN_RECHECK_SECONDS = 600


def resolve_google_drive_oauth_token(integration_id: int, team_id: int, force_refresh: bool = False) -> str:
    """Return the current access token for a Google Drive integration, refreshing it when stale.

    `force_refresh` is for the 401-mid-sync case: the row's stated expiry can be wrong once the grant
    is revoked or the token is invalidated early, so the caller asks for a re-mint before giving up.
    """
    try:
        integration = Integration.objects.get(id=integration_id, team_id=team_id, kind=GOOGLE_DRIVE_INTEGRATION_KIND)
    except Integration.DoesNotExist:
        raise ValueError(f"Integration not found: {integration_id}") from None

    oauth = OauthIntegration(integration)
    if force_refresh or oauth.access_token_expired():
        # Records the failure on the row rather than raising, so a still-stale token falls through
        # to the caller and surfaces as a 401 the user can act on.
        oauth.refresh_access_token()

    token = integration.access_token
    if not token:
        raise ValueError(MISSING_ACCESS_TOKEN_ERROR)
    return token
