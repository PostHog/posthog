from collections.abc import Mapping
from typing import Literal

from django.conf import settings

from posthog.models.instance_setting import get_instance_settings

OAuthCredentialsSource = Literal["slack_app", "slack_dev_app"]

_TRUSTED_OAUTH_METADATA_BY_SOURCE: dict[str, dict[str, str]] = {
    "slack_app": {
        "issuer": "https://mcp.slack.com",
        "authorization_endpoint": "https://slack.com/oauth/v2_user/authorize",
        "token_endpoint": "https://slack.com/api/oauth.v2.user.access",
    },
    "slack_dev_app": {
        "issuer": "https://mcp.slack.com",
        "authorization_endpoint": "https://slack.com/oauth/v2_user/authorize",
        "token_endpoint": "https://slack.com/api/oauth.v2.user.access",
    },
}

SUPPORTED_OAUTH_CREDENTIAL_SOURCES = frozenset(_TRUSTED_OAUTH_METADATA_BY_SOURCE)


def oauth_credentials_source_is_allowed(source: str, team_id: int) -> bool:
    return source != "slack_dev_app" or str(team_id) in settings.MCP_STORE_SLACK_DEV_ALLOWED_TEAM_IDS


def validate_oauth_credentials_source_metadata(source: str, metadata: Mapping[str, object]) -> None:
    trusted_metadata = _TRUSTED_OAUTH_METADATA_BY_SOURCE.get(source)
    if trusted_metadata is None:
        raise ValueError(f"Unknown OAuth credential source: {source}")
    if any(metadata.get(key) != value for key, value in trusted_metadata.items()):
        raise ValueError(f"OAuth metadata for credential source '{source}' does not match its trusted endpoints")


def resolve_oauth_credentials_source(source: str) -> dict[str, str]:
    if source not in SUPPORTED_OAUTH_CREDENTIAL_SOURCES:
        raise ValueError(f"Unknown OAuth credential source: {source}")

    prefix = "SLACK_DEV_APP" if source == "slack_dev_app" else "SLACK_APP"
    instance_settings = get_instance_settings([f"{prefix}_CLIENT_ID", f"{prefix}_CLIENT_SECRET"])
    client_id = instance_settings.get(f"{prefix}_CLIENT_ID")
    client_secret = instance_settings.get(f"{prefix}_CLIENT_SECRET")
    return {
        "client_id": client_id if isinstance(client_id, str) else "",
        "client_secret": client_secret if isinstance(client_secret, str) else "",
    }


def oauth_credentials_source_is_configured(source: str) -> bool:
    credentials = resolve_oauth_credentials_source(source)
    return bool(credentials["client_id"] and credentials["client_secret"])
