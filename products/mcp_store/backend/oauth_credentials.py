from collections.abc import Mapping
from typing import Literal

from posthog.models.instance_setting import get_instance_settings

OAuthCredentialsSource = Literal["slack_app"]

_TRUSTED_OAUTH_METADATA_BY_SOURCE: dict[str, dict[str, str]] = {
    "slack_app": {
        "issuer": "https://mcp.slack.com",
        "authorization_endpoint": "https://slack.com/oauth/v2_user/authorize",
        "token_endpoint": "https://slack.com/api/oauth.v2.user.access",
    }
}

SUPPORTED_OAUTH_CREDENTIAL_SOURCES = frozenset(_TRUSTED_OAUTH_METADATA_BY_SOURCE)


def validate_oauth_credentials_source_metadata(source: str, metadata: Mapping[str, object]) -> None:
    trusted_metadata = _TRUSTED_OAUTH_METADATA_BY_SOURCE.get(source)
    if trusted_metadata is None:
        raise ValueError(f"Unknown OAuth credential source: {source}")
    if any(metadata.get(key) != value for key, value in trusted_metadata.items()):
        raise ValueError(f"OAuth metadata for credential source '{source}' does not match its trusted endpoints")


def resolve_oauth_credentials_source(source: str) -> dict[str, str]:
    if source != "slack_app":
        raise ValueError(f"Unknown OAuth credential source: {source}")

    settings = get_instance_settings(["SLACK_APP_CLIENT_ID", "SLACK_APP_CLIENT_SECRET"])
    client_id = settings.get("SLACK_APP_CLIENT_ID")
    client_secret = settings.get("SLACK_APP_CLIENT_SECRET")
    return {
        "client_id": client_id if isinstance(client_id, str) else "",
        "client_secret": client_secret if isinstance(client_secret, str) else "",
    }


def oauth_credentials_source_is_configured(source: str) -> bool:
    credentials = resolve_oauth_credentials_source(source)
    return bool(credentials["client_id"] and credentials["client_secret"])
