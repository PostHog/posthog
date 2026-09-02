from typing import Literal

from posthog.models.instance_setting import get_instance_settings

OAuthCredentialsSource = Literal["slack_app"]

SUPPORTED_OAUTH_CREDENTIAL_SOURCES = frozenset({"slack_app"})


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
