import base64
import hashlib
import secrets
from urllib.parse import urlparse

import requests
import structlog

logger = structlog.get_logger(__name__)

TIMEOUT = 10


def _fetch_auth_server_metadata(auth_server_url: str) -> dict:
    parsed = urlparse(auth_server_url)
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


def discover_oauth_metadata(server_url: str) -> dict:
    parsed_server = urlparse(server_url)
    origin = f"{parsed_server.scheme}://{parsed_server.netloc}"
    path = parsed_server.path.rstrip("/")

    # Step 1: Try RFC 9728 Protected Resource Metadata to find the authorization server
    resource_url = f"{origin}/.well-known/oauth-protected-resource{path}"
    resource_resp = requests.get(resource_url, timeout=TIMEOUT)
    if resource_resp.status_code == 404 and path:
        resource_resp = requests.get(f"{origin}/.well-known/oauth-protected-resource", timeout=TIMEOUT)

    if resource_resp.ok:
        resource_data = resource_resp.json()
        auth_servers = resource_data.get("authorization_servers", [])
        if auth_servers:
            return _fetch_auth_server_metadata(auth_servers[0])

    # Step 2: Fall back to fetching authorization server metadata directly from the origin.
    # Many MCP servers (e.g. Linear) serve /.well-known/oauth-authorization-server
    # without implementing the protected resource metadata endpoint.
    return _fetch_auth_server_metadata(origin)


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
