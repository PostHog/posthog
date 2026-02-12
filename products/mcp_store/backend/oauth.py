import base64
import hashlib
import secrets
from urllib.parse import urlparse

import requests
import structlog

logger = structlog.get_logger(__name__)

TIMEOUT = 10


def discover_oauth_metadata(server_url: str) -> dict:
    origin = f"{urlparse(server_url).scheme}://{urlparse(server_url).netloc}"

    # RFC 9728: OAuth Protected Resource Metadata
    resource_url = f"{origin}/.well-known/oauth-protected-resource"
    resource_resp = requests.get(resource_url, timeout=TIMEOUT)
    resource_resp.raise_for_status()
    resource_data = resource_resp.json()

    auth_servers = resource_data.get("authorization_servers", [])
    if not auth_servers:
        raise ValueError("No authorization_servers found in protected resource metadata")

    auth_server = auth_servers[0]

    # RFC 8414: OAuth Authorization Server Metadata
    parsed = urlparse(auth_server)
    metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server"
    if parsed.path and parsed.path != "/":
        metadata_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-authorization-server{parsed.path}"

    metadata_resp = requests.get(metadata_url, timeout=TIMEOUT)
    metadata_resp.raise_for_status()
    metadata = metadata_resp.json()

    for field in ("authorization_endpoint", "token_endpoint"):
        if field not in metadata:
            raise ValueError(f"Missing required field '{field}' in authorization server metadata")

    return metadata


def register_dcr_client(metadata: dict, redirect_uri: str) -> str:
    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise ValueError("Authorization server does not support Dynamic Client Registration")

    resp = requests.post(
        registration_endpoint,
        json={
            "client_name": "MCP Store (PostHog)",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()

    client_id = data.get("client_id")
    if not client_id:
        raise ValueError("No client_id in DCR response")

    return client_id


def generate_pkce() -> tuple[str, str]:
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge
